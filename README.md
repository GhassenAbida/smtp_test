# SMTP Email Campaign System

A Python-based email campaign system with advanced SMTP connection pooling, rate limiting, and deliverability optimization. Designed for high-volume email sending with robust error handling and graceful degradation.

## Features

- **Multi-SMTP Support**: Load balance across multiple SMTP providers
- **Connection Pooling**: Persistent SMTP connections with round-robin rotation
- **Graceful Degradation**: Automatically removes failed SMTP connections and continues
- **Rate Limiting**: Configurable delays and test email verification
- **Deliverability Optimized**: Clean headers following Microsoft/Hotmail best practices
- **Duplicate Prevention**: Automatic filtering of sent emails and duplicates
- **Test Mode**: Safe testing with designated test recipients
- **Link Personalization**: Dynamic URL generation with recipient tracking
- **Statistics**: Detailed campaign reporting and SMTP usage analytics

## Quick Start

### 1. Installation

```bash
pip install aiosmtplib
```

### 2. Configuration Files

Create the following configuration files:

#### `smtp.json` - SMTP Configuration
```json
[
  {
    "host": "smtp.resend.com",
    "port": 587,
    "username": "resend",
    "password": "your_api_key",
    "encryption": "tls",
    "from_address": "billing@takeatest.net",
    "from_name": "Billing Team"
  },
  {
    "host": "smtp.zeptomail.com",
    "port": 587,
    "username": "emailapikey",
    "password": "your_api_key",
    "encryption": "tls",
    "from_address": "support@takeatest.net",
    "from_name": "Support Team"
  }
]
```

#### `recipients.txt` - Email Recipients
```
user1@example.com
user2@example.com
user3@example.com
```

#### `subject.txt` - Email Subject
```
Your subscription will be on hold soon!
```

#### `letter.html` - Email Template
```html
<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <title>Subscription Notice</title>
</head>
<body style="margin:0; padding:0; font-family: Arial, sans-serif;">
  <!-- Your email content here -->
</body>
</html>
```

#### `link.txt` - Base URL for Personalization
```
https://takeatest.net/access
```

#### `test_recipient.txt` - Test Email Address
```
test@example.com
```

#### `rate_limit.json` - Rate Limiting Configuration (Optional)
```json
{
  "wait_before_sending": 1.0,
  "test_index": 500
}
```

### 3. Running the Campaign

#### Production Mode
```bash
python smtp.py
```

#### Test Mode (Only sends to test recipients)
```bash
python smtp.py --test
```

## Project Structure

```
smtp/
├── smtp.py                 # Main application
├── models/
│   ├── __init__.py        # SMTPCredentials model
│   └── connection_pool.py # SMTP connection pool management
├── smtp.json              # SMTP configurations
├── recipients.txt         # Email recipients
├── subject.txt           # Email subject
├── letter.html           # Email template
├── link.txt              # Base URL for personalization
├── test_recipient.txt    # Test email addresses
├── rate_limit.json       # Rate limiting settings
├── send_success.txt      # Log of successful sends (auto-generated)
├── failed_recipients.txt # Log of failed sends (auto-generated)
├── erroned_smtp.json     # Failed SMTP configs (auto-generated)
└── statistics.txt        # Campaign statistics (auto-generated)
```

## Configuration Details

### SMTP Configuration
- Supports multiple SMTP providers
- Automatic failover and error handling
- Failed configurations moved to `erroned_smtp.json`

### Rate Limiting
- `wait_before_sending`: Delay between emails (seconds)
- `test_index`: Send test email every N regular emails

### Email Headers
Optimized for Microsoft/Hotmail deliverability:
- Standard RFC-compliant headers only
- No "bulk-y" marketing headers
- Proper authentication preparation (SPF/DKIM/DMARC ready)
- List-Unsubscribe headers for compliance

## Advanced Features

### Connection Pooling
- One persistent connection per SMTP account
- Round-robin email distribution
- Automatic connection health monitoring
- Failed connection removal and cleanup

### Error Handling
- **Graceful Degradation**: Continues with remaining SMTPs when one fails
- **Retry Logic**: Smart retry for connection errors
- **Error Logging**: Detailed failure tracking
- **Duplicate Prevention**: Automatic filtering of already-sent emails

### Test System
- Periodic test emails to verify system health
- Campaign stops if test emails fail
- Separate test mode for safe development

### Link Personalization
- Automatic URL replacement with personalized links
- Recipient email and timestamp tracking
- Configurable base URL via `link.txt`

## Monitoring & Analytics

### Output Files
- `send_success.txt`: Successfully sent email addresses
- `failed_recipients.txt`: Failed sends with error details
- `erroned_smtp.json`: Failed SMTP configurations
- `statistics.txt`: Campaign performance metrics

### Real-time Monitoring
- Connection pool status
- Send success/failure counts
- SMTP performance metrics
- Test email results

## Best Practices

### Email Deliverability
1. **Authentication**: Configure SPF, DKIM, and DMARC for your domain
2. **Reputation**: Use dedicated IPs and warm them up gradually
3. **Content**: Maintain text/HTML multipart messages
4. **Lists**: Keep recipients engaged and remove inactive emails
5. **Compliance**: Honor unsubscribe requests promptly

### System Management
1. **Testing**: Always test with `--test` mode first
2. **Monitoring**: Watch for failed SMTPs and error patterns
3. **Scaling**: Add more SMTP providers for higher volume
4. **Maintenance**: Regular cleanup of failed recipients and SMTPs

## Troubleshooting

### Common Issues

**Campaign stops unexpectedly**
- Check test email configuration
- Verify SMTP credentials are valid
- Review `erroned_smtp.json` for failed configurations

**Poor deliverability**
- Verify SPF/DKIM/DMARC records
- Check sender reputation
- Review email content for spam indicators
- Monitor Microsoft SNDS and JMRP

**Connection errors**
- Verify SMTP server settings
- Check network connectivity
- Review rate limiting settings
- Monitor concurrent connection limits

## License

This project is provided as-is for educational and legitimate business use only. Users are responsible for compliance with anti-spam laws and email service provider terms of service.

## Support

For issues and questions:
1. Review the troubleshooting section
2. Check configuration files for syntax errors
3. Monitor output logs for error details
4. Verify SMTP provider settings and quotas