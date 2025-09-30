#!/usr/bin/env python3
"""
SMTP Email Sender with file-based configuration.
Sends HTML emails to multiple recipients with rate limiting.
"""

import asyncio
import json
import logging
import os
from datetime import datetime
from email.message import EmailMessage
from typing import List
import aiosmtplib

from models import SMTPCredentials

# ----------------------------------------------------------------------
# File reading utilities
# ----------------------------------------------------------------------

def load_smtp_config(file_path: str = "smtp.json") -> SMTPCredentials:
    """Load SMTP configuration from JSON file."""
    if not os.path.exists(file_path):
        raise FileNotFoundError(f"SMTP config file not found: {file_path}")
    
    with open(file_path, 'r', encoding='utf-8') as f:
        config = json.load(f)
    
    return SMTPCredentials(
        host=config["host"],
        port=config["port"],
        username=config["username"],
        password=config["password"],
        encryption=config["encryption"],
        from_address=config["from_address"],
        from_name=config["from_name"]
    )


def load_recipients(file_path: str = "recipients.txt") -> List[str]:
    """Load recipient email addresses from text file (one per line), removing duplicates."""
    if not os.path.exists(file_path):
        raise FileNotFoundError(f"Recipients file not found: {file_path}")
    
    # First, read all recipients including duplicates
    with open(file_path, 'r', encoding='utf-8') as f:
        all_recipients = [line.strip() for line in f if line.strip()]
    
    original_count = len(all_recipients)
    
    # Remove duplicates while preserving order
    unique_recipients = []
    seen = set()
    for email in all_recipients:
        if email.lower() not in seen:  # Case-insensitive duplicate check
            unique_recipients.append(email)
            seen.add(email.lower())
    
    duplicates_removed = original_count - len(unique_recipients)
    
    if duplicates_removed > 0:
        logging.info(f"Removed {duplicates_removed} duplicate email(s) from recipients list")
        # Update the file with unique recipients
        with open(file_path, 'w', encoding='utf-8') as f:
            for email in unique_recipients:
                f.write(email + '\n')
        logging.info(f"Updated {file_path} with {len(unique_recipients)} unique recipients")
    else:
        logging.info("No duplicate emails found in recipients list")
    
    return unique_recipients


def load_subject(file_path: str = "subject.txt") -> str:
    """Load email subject from text file."""
    if not os.path.exists(file_path):
        raise FileNotFoundError(f"Subject file not found: {file_path}")
    
    with open(file_path, 'r', encoding='utf-8') as f:
        return f.read().strip()


def load_letter_html(file_path: str = "letter.html") -> str:
    """Load HTML email content from file."""
    if not os.path.exists(file_path):
        raise FileNotFoundError(f"Letter HTML file not found: {file_path}")
    
    with open(file_path, 'r', encoding='utf-8') as f:
        return f.read()


def load_rate_limit_config(file_path: str = "rate_limit.json") -> dict:
    """Load rate limiting configuration from JSON file."""
    if not os.path.exists(file_path):
        logging.warning(f"Rate limit config file not found: {file_path}, using defaults")
        return {"emails_per_batch": 1, "seconds_per_batch": 1}
    
    with open(file_path, 'r', encoding='utf-8') as f:
        config = json.load(f)
    
    # Validate configuration
    emails_per_batch = config.get("emails_per_batch", 1)
    seconds_per_batch = config.get("seconds_per_batch", 1)
    
    if emails_per_batch <= 0:
        logging.warning("emails_per_batch must be positive, using default value 1")
        emails_per_batch = 1
    
    if seconds_per_batch < 0:
        logging.warning("seconds_per_batch cannot be negative, using default value 1")
        seconds_per_batch = 1
    
    return {
        "emails_per_batch": emails_per_batch,
        "seconds_per_batch": seconds_per_batch
    }


def load_test_recipient(file_path: str = "test_recipient.txt") -> str:
    """Load test recipient email address from text file."""
    if not os.path.exists(file_path):
        logging.warning(f"Test recipient file not found: {file_path}, using hardcoded default")
        return "rahamtulla9@rediffmail.com"
    
    with open(file_path, 'r', encoding='utf-8') as f:
        test_email = f.read().strip()
    
    if not test_email:
        logging.warning("Test recipient file is empty, using hardcoded default")
        return "rahamtulla9@rediffmail.com"
    
    return test_email


# ----------------------------------------------------------------------
# Email sending functions
# ----------------------------------------------------------------------

def create_html_email_message(from_addr: str, from_name: str, to_addr: str, subject: str, html_content: str) -> EmailMessage:
    """Create HTML email message."""
    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = f"{from_name} <{from_addr}>"
    msg["To"] = to_addr
    msg.set_content(html_content, subtype="html")
    return msg


async def send_html_email_directly(
    host: str,
    port: int,
    username: str,
    password: str,
    from_addr: str,
    from_name: str,
    to_addr: str,
    subject: str,
    html_content: str,
    use_tls: bool = True,
    timeout: float = 30.0,
) -> dict:
    """Send HTML email using aiosmtplib."""
    start_time = datetime.now()
    try:
        message = create_html_email_message(from_addr, from_name, to_addr, subject, html_content)
        smtp = aiosmtplib.SMTP(hostname=host, port=port, timeout=timeout, use_tls=False, start_tls=False)
        await smtp.connect()
        if use_tls:
            await smtp.starttls()
        await smtp.login(username, password)
        await smtp.send_message(message)
        await smtp.quit()
        duration = (datetime.now() - start_time).total_seconds()
        return {"success": True, "message": f"Email sent to {to_addr}", "duration_seconds": duration, "mode": "STARTTLS"}
    except Exception as e:
        duration = (datetime.now() - start_time).total_seconds()
        return {"success": False, "error": str(e), "error_type": type(e).__name__, "duration_seconds": duration}


async def send_test_email(smtp_config: SMTPCredentials, test_recipient: str, subject: str, html_content: str, test_number: int) -> bool:
    """Send a test email to verify connection is still working."""
    test_subject = f"[TEST #{test_number}] {subject}"
    
    print(f"  🧪 Sending test email #{test_number} to: {test_recipient}")
    
    result = await send_html_email_directly(
        host=smtp_config.host,
        port=smtp_config.port,
        username=smtp_config.username,
        password=smtp_config.password,
        from_addr=smtp_config.from_address,
        from_name=smtp_config.from_name,
        to_addr=test_recipient,
        subject=test_subject,
        html_content=html_content,
    )
    
    if result["success"]:
        print(f"  ✅ Test email SUCCESS - Duration: {result['duration_seconds']:.2f}s")
        return True
    else:
        print(f"  ❌ Test email FAILED - {result['error_type']}: {result['error']}")
        return False


async def send_emails_with_rate_limit(smtp_config: SMTPCredentials, recipients: List[str], subject: str, html_content: str, rate_config: dict, test_recipient: str):
    """Send emails to all recipients with configurable rate limiting and test emails every 500 sends."""
    emails_per_batch = rate_config["emails_per_batch"]
    seconds_per_batch = rate_config["seconds_per_batch"]
    
    print(f"Starting email campaign to {len(recipients)} recipients...")
    print(f"Rate limit: {emails_per_batch} email(s) every {seconds_per_batch} second(s)")
    print(f"Test email: Every 500 emails to {test_recipient}")
    print("=" * 60)
    
    successful_sends = 0
    failed_sends = 0
    test_count = 0
    
    for i, recipient in enumerate(recipients, 1):
        # Send test email every 500 regular emails
        if i % 500 == 0:
            test_count += 1
            test_success = await send_test_email(smtp_config, test_recipient, subject, html_content, test_count)
            
            if not test_success:
                print(f"\n❌ TEST EMAIL FAILED! Stopping campaign at email #{i}")
                print(f"Last successful position: {i-1}")
                print("=" * 60)
                print(f"Campaign STOPPED due to test email failure!")
                print(f"Successful sends: {successful_sends}")
                print(f"Failed sends: {failed_sends}")
                print(f"Stopped at recipient: {i}/{len(recipients)}")
                return False
            
            print(f"  ✅ Test passed, continuing with regular emails...")
        
        print(f"[{i}/{len(recipients)}] Sending to: {recipient}")
        
        result = await send_html_email_directly(
            host=smtp_config.host,
            port=smtp_config.port,
            username=smtp_config.username,
            password=smtp_config.password,
            from_addr=smtp_config.from_address,
            from_name=smtp_config.from_name,
            to_addr=recipient,
            subject=subject,
            html_content=html_content,
        )
        
        if result["success"]:
            successful_sends += 1
            print(f"  ✓ Success - Duration: {result['duration_seconds']:.2f}s")
        else:
            failed_sends += 1
            print(f"  ✗ Failed - {result['error_type']}: {result['error']}")
        
        # Apply rate limiting - wait after sending a batch of emails
        if i % emails_per_batch == 0 and i < len(recipients):
            if seconds_per_batch > 0:
                print(f"  ⏳ Rate limiting: waiting {seconds_per_batch} second(s)...")
                await asyncio.sleep(seconds_per_batch)
    
    print("=" * 60)
    print(f"Campaign completed successfully!")
    print(f"Successful sends: {successful_sends}")
    print(f"Failed sends: {failed_sends}")
    print(f"Total recipients: {len(recipients)}")
    print(f"Test emails sent: {test_count}")
    print(f"Rate limit used: {emails_per_batch} email(s) every {seconds_per_batch} second(s)")
    return True


# ----------------------------------------------------------------------
# Main function
# ----------------------------------------------------------------------

async def main():
    """Main function to run the email campaign."""
    print("=" * 60)
    print("SMTP Email Campaign")
    print("=" * 60)

    logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")

    try:
        # Load configuration files
        print("Loading configuration files...")
        smtp_config = load_smtp_config()
        recipients = load_recipients()
        subject = load_subject()
        html_content = load_letter_html()
        rate_config = load_rate_limit_config()
        test_recipient = load_test_recipient()
        
        print(f"SMTP Server: {smtp_config.host}:{smtp_config.port}")
        print(f"From: {smtp_config.from_name} <{smtp_config.from_address}>")
        print(f"Subject: {subject}")
        print(f"Recipients loaded: {len(recipients)}")
        print(f"Test recipient: {test_recipient}")
        print(f"Encryption: {smtp_config.encryption}")
        print(f"Rate limit: {rate_config['emails_per_batch']} email(s) every {rate_config['seconds_per_batch']} second(s)")
        print()
        
        # Start email campaign
        campaign_success = await send_emails_with_rate_limit(smtp_config, recipients, subject, html_content, rate_config, test_recipient)
        
        if not campaign_success:
            print("\n⚠️  Campaign was stopped due to test email failure.")
            print("Check your SMTP configuration and network connection.")
        
    except FileNotFoundError as e:
        print(f"Configuration error: {e}")
        print("Please ensure all required files exist:")
        print("  - smtp.json (SMTP configuration)")
        print("  - recipients.txt (email addresses, one per line)")
        print("  - subject.txt (email subject)")
        print("  - letter.html (HTML email content)")
        print("  - rate_limit.json (rate limiting configuration - optional)")
        print("  - test_recipient.txt (test email address - optional, defaults to hardcoded)")
    except Exception as e:
        print(f"Unexpected error: {e}")


if __name__ == "__main__":
    asyncio.run(main())
