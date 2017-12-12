# wordpress-s3-backup
Backup multiple wordpress applications to s3

Usage:
```
python backup.py bucket_name /path/to/wordpress -p /path/to/another/wordpress -p /path/to/another/wordpress -a access_aws_key -s secret_aws_key -r region
```

Required: bucket_name and first /path/to/wordpress

Credentials will be get from env or AWS Config or AWS Credentials files

MIT
