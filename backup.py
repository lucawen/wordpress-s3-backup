import datetime
import boto3
import os
import sys
import re
import subprocess
import shutil
import tarfile
import pathlib
import argparse


class S3Client(object):
    client = None
    BUCKET_NAME = ''

    def __init__(self, bucket, access_key=None, secret_key=None, region=None):
        """
        Inicializa o cliente S3.

        Se fornecido access_key, secret_key e region, será priorizado a
        coenxão pelos parâmetros, caso contrário será via environment,
        AWS Config ou Credencial Compartilhada.
        """
        self.BUCKET_NAME = bucket
        if access_key and secret_key and region:
            self.client = boto3.client(
                's3',
                aws_access_key_id=access_key,
                aws_secret_access_key=secret_key,
                region_name=region
            )
        else:
            self.client = boto3.resource('s3')

    def upload(self, file_path):
        """
        Enviar um arquivo para o Bucket S3.

        Necessita de um path de um arquivo válido.
        """
        file_name = os.path.basename(file_path)
        self.client.upload_file(file_path, self.BUCKET_NAME, file_name)

    def delete(self, file_name):
        """Remove um arquivo do BUcket S3 configurado a partir de um nome."""
        self.client.delete_object(Bucket=self.BUCKET_NAME, Key=file_name)

    def list(self):
        """Retorna uma lista de strings com os nomes dos arquivos no bucket."""
        arr_its = []
        content = self.client.list_objects(Bucket=self.BUCKET_NAME)
        if 'Contents' in content:
            for key in content['Contents']:
                arr_its.append(key['Key'])
        return arr_its


class BackupWP(object):

    def __init__(self, bucket, access_key=None, secret_key=None, region=None):
        self.BACKUP_DIRECTORY = '/tmp/wpbackup'
        self.s3 = S3Client(
            bucket, access_key=access_key, secret_key=secret_key,
            region=region)

    def parsing_wpconfig(self, install_location):
        """Faz um parse das configurações do wordpress para um dicionário."""
        try:
            print('{:<5}{:30}{:^2}'.format(
                'LOG: ', 'Parsing wp-config.php File', ':'), end='')
            config_path = os.path.normpath(install_location + '/wp-config.php')
            with open(config_path) as fh:
                    content = fh.read()
            regex_db = r'define\(\s*?\'DB_NAME\'\s*?,\s*?\'(?P<DB>.*?)\'\s*?\);'
            regex_user = r'define\(\s*?\'DB_USER\'\s*?,\s*?\'(?P<USER>.*?)\'\s*?\);'
            regex_pass = r'define\(\s*?\'DB_PASSWORD\'\s*?,\s*?\'(?P<PASSWORD>.*?)\'\s*?\);'
            regex_host = r'define\(\s*?\'DB_HOST\'\s*?,\s*?\'(?P<HOST>.*?)\'\s*?\);'
            databse = re.search(regex_db, content).group('DB')
            user = re.search(regex_user, content).group('USER')
            password = re.search(regex_pass, content).group('PASSWORD')
            host = re.search(regex_host, content).group('HOST')
            print('Completed')
            return {
                'database': databse,
                'user': user,
                'password': password,
                'host': host
            }

        except FileNotFoundError:
            print('Falied')
            print('File Not Found,', config_path)
            sys.exit(1)
        except PermissionError:
            print('Falied')
            print('Unable To read Permission Denied,', config_path)
            sys.exit(1)
        except AttributeError:
            print('Falied')
            print('Parsing Error wp-config.php seems to be corrupt,')
            sys.exit(1)

    def take_sqldump(self, db_details):
        """Cria um backup do db."""
        print('{:<5}{:30}{:^2}'.format(
            'LOG: ', 'Creating DataBase Dump', ':'), end='')

        try:
            USER = db_details['user']
            PASSWORD = db_details['password']
            HOST = db_details['host']
            DATABASE = db_details['database']
            DUMPNAME = os.path.normpath(os.path.join(
                self.BACKUP_DIRECTORY, db_details['database'] + '.sql'))
            cmd = "mysqldump  -u {} -p{} -h {} {}  > {} 2> /dev/null".format(
                USER, PASSWORD, HOST, DATABASE, DUMPNAME)
            subprocess.check_output(cmd, shell=True)
            print('Completed')
            return DUMPNAME

        except subprocess.CalledProcessError:
            print('Failed')
            print(': MysqlDump Failed.')
            sys.exit(1)
        except Exception:
            print('Failed')
            print(': Unknown Error Occurred.')
            sys.exit(1)

    def make_archive(self, wordpress_path, dumpfile_path):
        """Pega os arquivos do wordpress e do dump do db e salva em um gzip."""
        try:
            print('{:<5}{:30}{:^2}'.format(
                'LOG: ', 'Archiving WordPress & SqlDump', ':'), end='')

            time_tag = datetime.datetime.now().strftime('%Y-%m-%d-%H-%M-%S')
            dir_name = os.path.basename(wordpress_path.rstrip('/'))
            f_name = dir_name + '_' + time_tag + '.tar.gz'
            archive_name = os.path.normpath(
                self.BACKUP_DIRECTORY + '/' + f_name)
            with tarfile.open(archive_name, "w:gz") as tar:
                tar.add(wordpress_path)
                tar.add(dumpfile_path, arcname="sql.dump")
            print('Completed')
            return archive_name

        except FileNotFoundError:
            print('Falied')
            print(': File Not Found,', archive_name)
            sys.exit(1)

        except PermissionError:
            print('Falied')
            print(': PermissionError Denied While Copying.')
            sys.exit(1)
        except Exception:
            print(
                ': Unknown error occurred while taring directory :',
                archive_name)
            sys.exit(1)

    def remove_backupdir(self):
        """Remove pasta de backup."""
        if os.path.exists(self.BACKUP_DIRECTORY):
            shutil.rmtree(self.BACKUP_DIRECTORY)

    def make_backupdir(self, location):
        """Cria pasta de backup."""
        if not os.path.exists(location):
            os.makedirs(location)

    def _find_array(self, arr, key):
        """Retorna o valor de um array que contem parte de seu valor."""
        for indx, it in enumerate(arr):
            if it.find(key) != -1:
                return arr[indx]

    def week_remove(self):
        """
        Remove o último arquivo do s3 se já tiver no limite de 7 arquivos.

        Para não ficar com muitos arquivos no s3, a cada 7 dias o último
        arquivo mais antigo é deletado para que um novo seja adicionado.
        """
        dates = []
        files = self.s3.list()
        for it in files:
            file_dt = it.split('_')[-1]
            ext_file = ''.join(pathlib.Path(file_dt).suffixes)
            try:
                dt_obj = datetime.datetime.strptime(
                    file_dt, '%Y-%m-%d-%H-%M-%S' + ext_file)
                dates.append(dt_obj)
            except ValueError:
                continue
        if len(dates) == 7:
            first_dt = sorted(dates)[0]
            dt_str = first_dt.strftime('%Y-%m-%d-%H-%M-%S')
            self.s3.delete(self._find_array(files, dt_str))

    def backup(self, location):
        if os.path.exists(location):
            print('')
            print('Backup Process of :', location)
            self.make_backupdir(self.BACKUP_DIRECTORY)
            database_info = self.parsing_wpconfig(location)
            dump_location = self.take_sqldump(database_info)
            archive_path = self.make_archive(location, dump_location)
            self.week_remove()
            self.s3.upload(archive_path)
        else:
            print('')
            print('Erro: Caminho não encontrado', location)
            print('')


parser = argparse.ArgumentParser(description='Backup wordpress aplications')
parser.add_argument('bucket', help='Bucket Name')
parser.add_argument('path', help='Path Wordpress Application')
parser.add_argument(
    '-p', action='append', dest='extra_path',
    help='More Wordpress applications')
parser.add_argument(
    '-a', action='store', dest='access_key', help='Access Key from AWS')
parser.add_argument(
    '-s', action='store', dest='secret_key', help='Secret Key from AWS')
parser.add_argument(
    '-r', action='store', dest='region', help='REGION from AWS')

options = parser.parse_args()

def main():
    if options.access_key and options.secret_key and options.region:
        bkp = BackupWP(
            options.bucket, access_key=options.access_key,
            secret_key=options.secret_key, region=options.region)

    arr_dirs = [options.path]
    if options.extra_path:
        arr_dirs.extend(options.extra_path)

    for location in arr_dirs:
        bkp.backup(location)
    bkp.remove_backupdir

if __name__ == '__main__':
    main()
