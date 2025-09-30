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

def load_smtp_config(file_path: str = "smtp.json") -> List[SMTPCredentials]:
    """Load SMTP configuration(s) from JSON file. Supports single config or array of configs."""
    if not os.path.exists(file_path):
        raise FileNotFoundError(f"SMTP config file not found: {file_path}")
    
    with open(file_path, 'r', encoding='utf-8') as f:
        config_data = json.load(f)
    
    # Handle both single config and array of configs
    if isinstance(config_data, list):
        # Multiple SMTP configurations
        smtp_configs = []
        for i, config in enumerate(config_data):
            try:
                smtp_configs.append(SMTPCredentials(
                    host=config["host"],
                    port=config["port"],
                    username=config["username"],
                    password=config["password"],
                    encryption=config["encryption"],
                    from_address=config["from_address"],
                    from_name=config["from_name"]
                ))
            except KeyError as e:
                logging.error(f"Missing key {e} in SMTP config #{i+1}, skipping")
                continue
        
        if not smtp_configs:
            raise ValueError("No valid SMTP configurations found")
        
        logging.info(f"Loaded {len(smtp_configs)} SMTP configuration(s)")
        return smtp_configs
    else:
        # Single SMTP configuration
        smtp_config = SMTPCredentials(
            host=config_data["host"],
            port=config_data["port"],
            username=config_data["username"],
            password=config_data["password"],
            encryption=config_data["encryption"],
            from_address=config_data["from_address"],
            from_name=config_data["from_name"]
        )
        logging.info("Loaded 1 SMTP configuration")
        return [smtp_config]


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
    defaults = {
        "connection": 3,
        "wait_before_sending": 1.0,
        "retry_if_error": 3,
        "rotate_per_smtp": 100
    }
    
    if not os.path.exists(file_path):
        logging.warning(f"Rate limit config file not found: {file_path}, using defaults")
        return defaults
    
    with open(file_path, 'r', encoding='utf-8') as f:
        config = json.load(f)
    
    # Validate configuration with defaults
    connection = config.get("connection", defaults["connection"])
    wait_before_sending = config.get("wait_before_sending", defaults["wait_before_sending"])
    retry_if_error = config.get("retry_if_error", defaults["retry_if_error"])
    rotate_per_smtp = config.get("rotate_per_smtp", defaults["rotate_per_smtp"])
    
    # Validate values
    
    if connection <= 0:
        logging.warning("connection must be positive, using default value")
        connection = defaults["connection"]
    elif connection > 10:
        logging.warning("connection should not exceed 10 for stability, using 10")
        connection = 10
    
    if wait_before_sending < 0:
        logging.warning("wait_before_sending cannot be negative, using default value")
        wait_before_sending = defaults["wait_before_sending"]
    
    if retry_if_error < 0:
        logging.warning("retry_if_error cannot be negative, using default value")
        retry_if_error = defaults["retry_if_error"]
    elif retry_if_error > 10:
        logging.warning("retry_if_error should not exceed 10, using 10")
        retry_if_error = 10
    
    if rotate_per_smtp <= 0:
        logging.warning("rotate_per_smtp must be positive, using default value")
        rotate_per_smtp = defaults["rotate_per_smtp"]
    
    return {
        "connection": connection,
        "wait_before_sending": wait_before_sending,
        "retry_if_error": retry_if_error,
        "rotate_per_smtp": rotate_per_smtp
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


def remove_successful_recipient(email: str, file_path: str = "recipients.txt"):
    """Remove a successfully sent email from the recipients file."""
    try:
        # Read all current recipients
        if not os.path.exists(file_path):
            logging.warning(f"Recipients file not found: {file_path}")
            return
        
        with open(file_path, 'r', encoding='utf-8') as f:
            all_recipients = [line.strip() for line in f if line.strip()]
        
        # Remove the successfully sent email (case-insensitive)
        original_count = len(all_recipients)
        updated_recipients = [recipient for recipient in all_recipients if recipient.lower() != email.lower()]
        
        if len(updated_recipients) < original_count:
            # Write back the updated list
            with open(file_path, 'w', encoding='utf-8') as f:
                for recipient in updated_recipients:
                    f.write(recipient + '\n')
            
            logging.info(f"Removed {email} from recipients list. Remaining: {len(updated_recipients)}")
        else:
            logging.warning(f"Email {email} not found in recipients list for removal")
            
    except Exception as e:
        logging.error(f"Error removing recipient {email}: {e}")


def save_failed_recipient(email: str, error_info: str, file_path: str = "failed_recipients.txt"):
    """Save failed email attempts to a separate file for later retry."""
    try:
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        with open(file_path, 'a', encoding='utf-8') as f:
            f.write(f"{timestamp} | {email} | {error_info}\n")
        logging.info(f"Logged failed send for {email} to {file_path}")
    except Exception as e:
        logging.error(f"Error logging failed recipient {email}: {e}")


def save_successful_recipient(email: str, smtp_info: str, file_path: str = "send_success.txt"):
    """Save successfully sent emails to a tracking file."""
    try:
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        with open(file_path, 'a', encoding='utf-8') as f:
            f.write(f"{timestamp} | {email} | {smtp_info}\n")
        logging.info(f"Logged successful send for {email} to {file_path}")
    except Exception as e:
        logging.error(f"Error logging successful recipient {email}: {e}")


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


async def send_html_email_with_retry(
    smtp_config: SMTPCredentials,
    to_addr: str,
    subject: str,
    html_content: str,
    retry_count: int = 3,
    connection_semaphore: asyncio.Semaphore = None,
    use_tls: bool = True,
    timeout: float = 30.0,
) -> dict:
    """Send HTML email with retry mechanism and connection limiting."""
    last_error = None
    
    for attempt in range(retry_count + 1):  # +1 for initial attempt
        try:
            # Use connection semaphore if provided
            if connection_semaphore:
                async with connection_semaphore:
                    result = await _send_single_email(smtp_config, to_addr, subject, html_content, use_tls, timeout)
            else:
                result = await _send_single_email(smtp_config, to_addr, subject, html_content, use_tls, timeout)
            
            if result["success"]:
                if attempt > 0:
                    result["retry_attempts"] = attempt
                return result
            else:
                last_error = result
                
        except Exception as e:
            last_error = {"success": False, "error": str(e), "error_type": type(e).__name__, "duration_seconds": 0}
        
        # Wait before retry (exponential backoff)
        if attempt < retry_count:
            wait_time = min(2 ** attempt, 30)  # Cap at 30 seconds
            await asyncio.sleep(wait_time)
    
    # All retries failed
    if last_error:
        last_error["retry_attempts"] = retry_count
        return last_error
    else:
        return {"success": False, "error": "Unknown error after retries", "retry_attempts": retry_count, "duration_seconds": 0}


async def _send_single_email(
    smtp_config: SMTPCredentials,
    to_addr: str,
    subject: str,
    html_content: str,
    use_tls: bool = True,
    timeout: float = 30.0,
) -> dict:
    """Internal function to send a single email."""
    start_time = datetime.now()
    try:
        message = create_html_email_message(smtp_config.from_address, smtp_config.from_name, to_addr, subject, html_content)
        smtp = aiosmtplib.SMTP(hostname=smtp_config.host, port=smtp_config.port, timeout=timeout, use_tls=False, start_tls=False)
        await smtp.connect()
        if use_tls:
            await smtp.starttls()
        await smtp.login(smtp_config.username, smtp_config.password)
        await smtp.send_message(message)
        await smtp.quit()
        duration = (datetime.now() - start_time).total_seconds()
        return {"success": True, "message": f"Email sent to {to_addr}", "duration_seconds": duration, "mode": "STARTTLS"}
    except Exception as e:
        duration = (datetime.now() - start_time).total_seconds()
        return {"success": False, "error": str(e), "error_type": type(e).__name__, "duration_seconds": duration}


# Legacy function for backward compatibility
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
    """Legacy function - creates SMTPCredentials and calls new function."""
    smtp_config = SMTPCredentials(host, port, username, password, "tls", from_addr, from_name)
    return await _send_single_email(smtp_config, to_addr, subject, html_content, use_tls, timeout)


async def send_test_email(smtp_config: SMTPCredentials, test_recipient: str, subject: str, html_content: str, test_number: int, retry_count: int = 3) -> bool:
    """Send a test email to verify connection is still working."""
    test_subject = f"[TEST #{test_number}] {subject}"
    
    print(f"  🧪 Sending test email #{test_number} to: {test_recipient}")
    
    result = await send_html_email_with_retry(
        smtp_config=smtp_config,
        to_addr=test_recipient,
        subject=test_subject,
        html_content=html_content,
        retry_count=retry_count
    )
    
    if result["success"]:
        retry_info = f" (after {result.get('retry_attempts', 0)} retries)" if result.get('retry_attempts', 0) > 0 else ""
        print(f"  ✅ Test email SUCCESS{retry_info} - Duration: {result['duration_seconds']:.2f}s")
        return True
    else:
        retry_info = f" (failed after {result.get('retry_attempts', 0)} retries)" if result.get('retry_attempts', 0) > 0 else ""
        print(f"  ❌ Test email FAILED{retry_info} - {result['error_type']}: {result['error']}")
        return False


async def send_emails_with_advanced_features(
    smtp_configs: List[SMTPCredentials], 
    recipients: List[str], 
    subject: str, 
    html_content: str, 
    rate_config: dict, 
    test_recipient: str
):
    """Send emails with all advanced features: connection pooling, retries, rotation, individual delays."""
    # Extract configuration
    connection_pool_size = rate_config["connection"]
    wait_before_sending = rate_config["wait_before_sending"]
    retry_if_error = rate_config["retry_if_error"]
    rotate_per_smtp = rate_config["rotate_per_smtp"]
    
    # Create connection semaphore for limiting concurrent connections
    connection_semaphore = asyncio.Semaphore(connection_pool_size)
    
    print(f"Starting advanced email campaign to {len(recipients)} recipients...")
    print(f"SMTP accounts: {len(smtp_configs)}")
    print(f"Connection pool: {connection_pool_size} simultaneous connections")
    print(f"Individual delay: {wait_before_sending}s before each email")
    print(f"Retry attempts: {retry_if_error}")
    print(f"SMTP rotation: Every {rotate_per_smtp} emails")
    print(f"Test email: Every 500 emails to {test_recipient}")
    print("=" * 80)
    
    successful_sends = 0
    failed_sends = 0
    test_count = 0
    current_smtp_index = 0
    
    for i, recipient in enumerate(recipients, 1):
        # Send test email every 500 regular emails
        if i % 500 == 0:
            test_count += 1
            current_smtp = smtp_configs[current_smtp_index % len(smtp_configs)]
            test_success = await send_test_email(current_smtp, test_recipient, subject, html_content, test_count, retry_if_error)
            
            if not test_success:
                print(f"\n❌ TEST EMAIL FAILED! Stopping campaign at email #{i}")
                print(f"Last successful position: {i-1}")
                print("=" * 80)
                print(f"Campaign STOPPED due to test email failure!")
                print(f"Successful sends: {successful_sends}")
                print(f"Failed sends: {failed_sends}")
                print(f"Stopped at recipient: {i}/{len(recipients)}")
                return False
            
            print(f"  ✅ Test passed, continuing with regular emails...")
        
        # Rotate SMTP account if needed
        if i % rotate_per_smtp == 0 and len(smtp_configs) > 1:
            current_smtp_index = (current_smtp_index + 1) % len(smtp_configs)
            current_smtp = smtp_configs[current_smtp_index]
            print(f"  🔄 Rotated to SMTP account #{current_smtp_index + 1}: {current_smtp.host}")
        else:
            current_smtp = smtp_configs[current_smtp_index % len(smtp_configs)]
        
        print(f"[{i}/{len(recipients)}] Sending to: {recipient} (SMTP #{current_smtp_index + 1})")
        
        # Apply individual email delay before sending
        if wait_before_sending > 0:
            await asyncio.sleep(wait_before_sending)
        
        # Send email with retry and connection pooling
        result = await send_html_email_with_retry(
            smtp_config=current_smtp,
            to_addr=recipient,
            subject=subject,
            html_content=html_content,
            retry_count=retry_if_error,
            connection_semaphore=connection_semaphore
        )
        
        if result["success"]:
            successful_sends += 1
            retry_info = f" (after {result.get('retry_attempts', 0)} retries)" if result.get('retry_attempts', 0) > 0 else ""
            print(f"  ✓ Success{retry_info} - Duration: {result['duration_seconds']:.2f}s")
            
            # Remove successfully sent email from recipients file
            remove_successful_recipient(recipient)
            print(f"  📝 Removed {recipient} from recipients list")
            
            # Log successful email to success tracking file
            smtp_info = f"SMTP #{current_smtp_index + 1}: {current_smtp.host}"
            save_successful_recipient(recipient, smtp_info)
            print(f"  ✅ Logged success to send_success.txt")
        else:
            failed_sends += 1
            retry_info = f" (failed after {result.get('retry_attempts', 0)} retries)" if result.get('retry_attempts', 0) > 0 else ""
            error_details = f"{result['error_type']}: {result['error']}"
            print(f"  ✗ Failed{retry_info} - {error_details}")
            
            # Log failed email for potential retry later
            save_failed_recipient(recipient, error_details)
        
        # No batch rate limiting - using only individual delays
    
    print("=" * 80)
    print(f"Campaign completed successfully!")
    print(f"Successful sends: {successful_sends} (removed from recipients.txt, logged to send_success.txt)")
    print(f"Failed sends: {failed_sends} (logged to failed_recipients.txt)")
    print(f"Total recipients processed: {len(recipients)}")
    print(f"Test emails sent: {test_count}")
    print(f"SMTP accounts used: {len(smtp_configs)}")
    print(f"Final SMTP account: #{current_smtp_index + 1}")
    
    # Show remaining recipients count
    try:
        with open("recipients.txt", 'r', encoding='utf-8') as f:
            remaining_count = len([line.strip() for line in f if line.strip()])
        print(f"Remaining recipients in file: {remaining_count}")
    except:
        print("Could not check remaining recipients count")
    
    return True


# Backward compatibility wrapper
async def send_emails_with_rate_limit(smtp_config: SMTPCredentials, recipients: List[str], subject: str, html_content: str, rate_config: dict, test_recipient: str):
    """Legacy wrapper function for backward compatibility."""
    return await send_emails_with_advanced_features([smtp_config], recipients, subject, html_content, rate_config, test_recipient)


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
        smtp_configs = load_smtp_config()
        recipients = load_recipients()
        subject = load_subject()
        html_content = load_letter_html()
        rate_config = load_rate_limit_config()
        test_recipient = load_test_recipient()
        
        # Display configuration summary
        print(f"SMTP accounts: {len(smtp_configs)}")
        for i, config in enumerate(smtp_configs, 1):
            print(f"  #{i}: {config.from_name} <{config.from_address}> via {config.host}:{config.port}")
        print(f"Subject: {subject}")
        print(f"Recipients loaded: {len(recipients)}")
        print(f"Test recipient: {test_recipient}")
        print(f"Advanced features:")
        print(f"  - Connection pool: {rate_config['connection']} simultaneous connections")
        print(f"  - Retry attempts: {rate_config['retry_if_error']}")
        print(f"  - Individual delay: {rate_config['wait_before_sending']}s")
        print(f"  - SMTP rotation: Every {rate_config['rotate_per_smtp']} emails")
        print()
        
        # Start advanced email campaign
        campaign_success = await send_emails_with_advanced_features(
            smtp_configs, recipients, subject, html_content, rate_config, test_recipient
        )
        
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
        print()
        print("Files created automatically:")
        print("  - send_success.txt (log of successful email sends)")
        print("  - failed_recipients.txt (log of failed email attempts)")
    except Exception as e:
        print(f"Unexpected error: {e}")


if __name__ == "__main__":
    asyncio.run(main())
