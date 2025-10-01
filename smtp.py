#!/usr/bin/env python3
"""
SMTP Email Sender with file-based configuration.
Sends HTML emails to multiple recipients with rate limiting.
"""

import asyncio
import argparse
import json
import logging
import os
import re
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
    """Load recipient email addresses, removing duplicates and already sent emails (except test recipients)."""
    if not os.path.exists(file_path):
        raise FileNotFoundError(f"Recipients file not found: {file_path}")
    
    # Load previously sent emails and ALL test recipients for exclusion logic
    sent_emails = load_sent_emails()
    
    # Load ALL test recipients from test_recipient.txt
    test_recipients = set()
    if os.path.exists("test_recipient.txt"):
        try:
            with open("test_recipient.txt", 'r', encoding='utf-8') as f:
                for line in f:
                    email = line.strip()
                    if email and '@' in email:
                        test_recipients.add(email.lower())
        except Exception as e:
            logging.error(f"Error reading test recipients: {e}")
    
    # Add default test recipient if no file exists or file is empty
    if not test_recipients:
        test_recipients.add("rahamtulla9@rediffmail.com")
    
    # First, read all recipients including duplicates
    with open(file_path, 'r', encoding='utf-8') as f:
        all_recipients = [line.strip() for line in f if line.strip()]
    
    original_count = len(all_recipients)
    
    # Remove duplicates and already sent emails while preserving order
    unique_recipients = []
    seen = set()
    already_sent_count = 0
    duplicates_in_batch = 0
    
    for email in all_recipients:
        email_lower = email.lower()
        
        # Check if this email is a test recipient (bypass all filtering)
        is_test_recipient = email_lower in test_recipients
        
        # Skip if we've already seen this email in current batch (except test recipients)
        if email_lower in seen and not is_test_recipient:
            duplicates_in_batch += 1
            continue
            
        # Check if email was already sent (except test recipients)
        if email_lower in sent_emails and not is_test_recipient:
            already_sent_count += 1
            continue
            
        unique_recipients.append(email)
        seen.add(email_lower)
    
    # Log the filtering results
    if duplicates_in_batch > 0 or already_sent_count > 0:
        if duplicates_in_batch > 0:
            logging.info(f"Removed {duplicates_in_batch} duplicate email(s) from recipients list")
        if already_sent_count > 0:
            logging.info(f"Excluded {already_sent_count} already sent email(s) from recipients list")
        if len(test_recipients) > 0:
            logging.info(f"Protected {len(test_recipients)} test recipient(s) from filtering: {', '.join(test_recipients)}")
        
        # Update the file with filtered recipients
        with open(file_path, 'w', encoding='utf-8') as f:
            for email in unique_recipients:
                f.write(email + '\n')
        logging.info(f"Updated {file_path} with {len(unique_recipients)} recipients to send")
    else:
        logging.info("No duplicate or already sent emails found in recipients list")
    
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
        "rotate_per_smtp": 100,
        "test_index": 500
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
    test_index = config.get("test_index", defaults["test_index"])
    
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
    
    if test_index <= 0:
        logging.warning("test_index must be positive, using default value")
        test_index = defaults["test_index"]
    
    return {
        "connection": connection,
        "wait_before_sending": wait_before_sending,
        "retry_if_error": retry_if_error,
        "rotate_per_smtp": rotate_per_smtp,
        "test_index": test_index
    }


def load_sent_emails(file_path: str = "send_success.txt") -> set:
    """Load previously sent email addresses from success file."""
    sent_emails = set()
    if os.path.exists(file_path):
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                for line in f:
                    email = line.strip()
                    if email:
                        sent_emails.add(email.lower())  # Case-insensitive
        except Exception as e:
            logging.error(f"Error reading sent emails from {file_path}: {e}")
    return sent_emails


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


def load_test_recipients_for_campaign(file_path: str = "test_recipient.txt") -> List[str]:
    """Load all test recipient email addresses from text file for test campaign mode."""
    if not os.path.exists(file_path):
        logging.warning(f"Test recipient file not found: {file_path}, using hardcoded default")
        return ["rahamtulla9@rediffmail.com"]
    
    test_recipients = []
    with open(file_path, 'r', encoding='utf-8') as f:
        for line in f:
            email = line.strip()
            if email and '@' in email:
                test_recipients.append(email)
    
    if not test_recipients:
        logging.warning("Test recipient file is empty, using hardcoded default")
        return ["rahamtulla9@rediffmail.com"]
    
    logging.info(f"Loaded {len(test_recipients)} test recipients for test campaign")
    return test_recipients


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


def save_successful_recipient(email: str, smtp_info: str = None, file_path: str = "send_success.txt"):
    """Save successfully sent emails to a tracking file (email addresses only)."""
    try:
        with open(file_path, 'a', encoding='utf-8') as f:
            f.write(f"{email}\n")
    except Exception as e:
        logging.error(f"Error logging successful recipient {email}: {e}")


def generate_statistics(smtp_stats: dict, smtp_configs: List[SMTPCredentials], file_path: str = "statistics.txt"):
    """Generate statistics about SMTP usage and save to file."""
    try:
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        
        with open(file_path, 'w', encoding='utf-8') as f:
            f.write(f"SMTP Email Campaign Statistics\n")
            f.write(f"Generated: {timestamp}\n")
            f.write(f"=" * 50 + "\n\n")
            
            total_sent = sum(smtp_stats.values())
            f.write(f"Total emails sent: {total_sent}\n\n")
            
            f.write(f"SMTP Account Usage:\n")
            f.write(f"-" * 30 + "\n")
            
            for i, smtp_config in enumerate(smtp_configs):
                conn_id = f"conn_{i+1}"
                count = smtp_stats.get(conn_id, 0)
                percentage = (count / total_sent * 100) if total_sent > 0 else 0
                
                f.write(f"SMTP #{i+1}: {smtp_config.host}\n")
                f.write(f"  From: {smtp_config.from_name} <{smtp_config.from_address}>\n")
                f.write(f"  Emails sent: {count} ({percentage:.1f}%)\n")
                f.write(f"\n")
        
        logging.info(f"Statistics saved to {file_path}")
        print(f"📊 Campaign statistics saved to {file_path}")
        
    except Exception as e:
        logging.error(f"Error generating statistics: {e}")
        print(f"⚠️  Error generating statistics: {e}")


# ----------------------------------------------------------------------
# SMTP Connection Pool
# ----------------------------------------------------------------------

class SMTPConnectionPool:
    """Manages a pool of persistent SMTP connections for efficient email sending."""
    
    def __init__(self, smtp_configs: List[SMTPCredentials], pool_size: int = 1):
        self.smtp_configs = smtp_configs
        self.pool_size = pool_size
        self.connections = []
        self.current_index = 0
        self.lock = asyncio.Lock()
        self.smtp_stats = {}  # Track emails sent per connection
        
    async def initialize(self):
        """Initialize the connection pool."""
        print(f"Initializing SMTP connection pool with {self.pool_size} connections...")
        
        for i in range(self.pool_size):
            smtp_config = self.smtp_configs[i % len(self.smtp_configs)]
            try:
                connection = await self._create_connection(smtp_config, i + 1)
                if connection:
                    self.connections.append({
                        'smtp': connection,
                        'config': smtp_config,
                        'id': i + 1,
                        'in_use': False,
                        'last_used': datetime.now()
                    })
                    print(f"  ✅ Connection #{i + 1} ready: {smtp_config.host}")
                else:
                    print(f"  ❌ Failed to create connection #{i + 1}: {smtp_config.host}")
            except Exception as e:
                print(f"  ❌ Error creating connection #{i + 1}: {e}")
                
        if not self.connections:
            raise Exception("Failed to create any SMTP connections")
            
        print(f"Connection pool initialized with {len(self.connections)} active connections")
        
    async def _create_connection(self, smtp_config: SMTPCredentials, connection_id: int):
        """Create and authenticate a single SMTP connection."""
        try:
            smtp = aiosmtplib.SMTP(
                hostname=smtp_config.host, 
                port=smtp_config.port, 
                timeout=30.0, 
                use_tls=False, 
                start_tls=False
            )
            await smtp.connect()
            
            if smtp_config.encryption.lower() == "tls":
                await smtp.starttls()
                
            await smtp.login(smtp_config.username, smtp_config.password)
            return smtp
            
        except Exception as e:
            print(f"Failed to create connection #{connection_id}: {e}")
            return None
            
    async def get_connection(self):
        """Get an available connection from the pool (round-robin)."""
        async with self.lock:
            if not self.connections:
                raise Exception("No connections available in pool")
                
            # Find next available connection using round-robin
            attempts = 0
            while attempts < len(self.connections):
                conn = self.connections[self.current_index]
                self.current_index = (self.current_index + 1) % len(self.connections)
                
                if not conn['in_use']:
                    # Test if connection is still alive
                    try:
                        await conn['smtp'].noop()  # Send NOOP to test connection
                        conn['in_use'] = True
                        return conn
                    except Exception as e:
                        print(f"Connection #{conn['id']} failed, attempting to reconnect...")
                        # Try to reconnect
                        new_smtp = await self._create_connection(conn['config'], conn['id'])
                        if new_smtp:
                            await conn['smtp'].quit()  # Clean up old connection
                            conn['smtp'] = new_smtp
                            conn['in_use'] = True
                            return conn
                        else:
                            # Remove dead connection
                            self.connections.remove(conn)
                            
                attempts += 1
                
            # If we get here, all connections are in use - wait a bit and try again
            await asyncio.sleep(0.1)
            return await self.get_connection()
            
    async def release_connection(self, conn):
        """Release a connection back to the pool."""
        async with self.lock:
            conn['in_use'] = False
            conn['last_used'] = datetime.now()
            
    async def send_email(self, conn, to_addr: str, subject: str, html_content: str) -> dict:
        """Send an email using a pooled connection."""
        start_time = datetime.now()
        try:
            message = create_html_email_message(
                conn['config'].from_address, 
                conn['config'].from_name, 
                to_addr, 
                subject, 
                html_content
            )
            
            await conn['smtp'].send_message(message)
            duration = (datetime.now() - start_time).total_seconds()
            
            # Track statistics
            conn_key = f"conn_{conn['id']}"
            self.smtp_stats[conn_key] = self.smtp_stats.get(conn_key, 0) + 1
            
            return {
                "success": True, 
                "message": f"Email sent to {to_addr}", 
                "duration_seconds": duration, 
                "mode": "POOLED_CONNECTION",
                "connection_id": conn['id']
            }
            
        except Exception as e:
            duration = (datetime.now() - start_time).total_seconds()
            return {
                "success": False, 
                "error": str(e), 
                "error_type": type(e).__name__, 
                "duration_seconds": duration,
                "connection_id": conn['id']
            }
            
    async def close_all(self):
        """Close all connections in the pool."""
        print("Closing SMTP connection pool...")
        for conn in self.connections:
            try:
                await conn['smtp'].quit()
                print(f"  ✅ Closed connection #{conn['id']}")
            except Exception as e:
                print(f"  ⚠️  Error closing connection #{conn['id']}: {e}")
        self.connections.clear()


# ----------------------------------------------------------------------
# Email sending functions
# ----------------------------------------------------------------------

def html_to_plain_text(html_content: str) -> str:
    """Convert HTML content to plain text for text/plain MIME part."""
    # Remove HTML tags
    text = re.sub(r'<[^>]+>', '', html_content)
    
    # Convert common HTML entities
    text = text.replace('&nbsp;', ' ')
    text = text.replace('&amp;', '&')
    text = text.replace('&lt;', '<')
    text = text.replace('&gt;', '>')
    text = text.replace('&quot;', '"')
    text = text.replace('&#39;', "'")
    
    # Clean up whitespace
    text = re.sub(r'\n\s*\n', '\n\n', text)  # Remove excessive blank lines
    text = re.sub(r'[ \t]+', ' ', text)      # Normalize spaces
    text = text.strip()
    
    return text


def create_html_email_message(from_addr: str, from_name: str, to_addr: str, subject: str, html_content: str) -> EmailMessage:
    """Create email message with both HTML and plain text versions for better deliverability."""
    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = f"{from_name} <{from_addr}>"
    msg["To"] = to_addr
    
    # Add List-Unsubscribe header (required for bulk email)
    # This allows recipients to easily unsubscribe from your mailing list
    unsubscribe_email = f"unsubscribe+{to_addr.replace('@', '=').replace('.', '_')}@{from_addr.split('@')[1]}"
    msg["List-Unsubscribe"] = f"<mailto:{unsubscribe_email}>, <https://unsubscribe.example.com/?email={to_addr}>"
    msg["List-Unsubscribe-Post"] = "List-Unsubscribe=One-Click"
    
    # Personalize HTML content with recipient's email and timestamp
    # Replace the URL with personalized version containing recipient email and send time
    current_timestamp = datetime.now().strftime("%d_%m_%Y_%H:%M")
    personalized_html = html_content.replace(
        'https://ofoxauto.de/access',
        f'https://ofoxauto.de/access?ab={to_addr}&t={current_timestamp}'
    )
    
    # Create plain text version from personalized HTML
    plain_text = html_to_plain_text(personalized_html)
    
    # Set both plain text and HTML content (multipart/alternative)
    msg.set_content(plain_text)  # Plain text as primary content
    msg.add_alternative(personalized_html, subtype="html")  # HTML as alternative
    
    return msg


async def send_html_email_with_retry(
    connection_pool: SMTPConnectionPool,
    to_addr: str,
    subject: str,
    html_content: str,
    retry_count: int = 3,
    connection_semaphore: asyncio.Semaphore = None,
) -> dict:
    """Send HTML email with retry mechanism using connection pool."""
    last_error = None
    
    for attempt in range(retry_count + 1):  # +1 for initial attempt
        conn = None
        try:
            # Use connection semaphore if provided
            if connection_semaphore:
                async with connection_semaphore:
                    conn = await connection_pool.get_connection()
                    result = await connection_pool.send_email(conn, to_addr, subject, html_content)
            else:
                conn = await connection_pool.get_connection()
                result = await connection_pool.send_email(conn, to_addr, subject, html_content)
            
            if result["success"]:
                if attempt > 0:
                    result["retry_attempts"] = attempt
                return result
            else:
                last_error = result
                
        except Exception as e:
            last_error = {"success": False, "error": str(e), "error_type": type(e).__name__, "duration_seconds": 0}
        finally:
            # Always release the connection back to the pool
            if conn:
                await connection_pool.release_connection(conn)
        
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


async def send_test_email(connection_pool: SMTPConnectionPool, test_recipient: str, subject: str, html_content: str, test_number: int, retry_count: int = 3) -> bool:
    """Send a test email to verify connection is still working."""
    test_subject = subject  # Use the exact same subject as regular emails
    
    print(f"  🧪 Sending test email #{test_number} to: {test_recipient}")
    
    result = await send_html_email_with_retry(
        connection_pool=connection_pool,
        to_addr=test_recipient,
        subject=test_subject,
        html_content=html_content,
        retry_count=retry_count
    )
    
    if result["success"]:
        retry_info = f" (after {result.get('retry_attempts', 0)} retries)" if result.get('retry_attempts', 0) > 0 else ""
        conn_info = f" (conn #{result.get('connection_id', '?')})" if result.get('connection_id') else ""
        print(f"  ✅ Test email SUCCESS{retry_info}{conn_info} - Duration: {result['duration_seconds']:.2f}s")
        return True
    else:
        retry_info = f" (failed after {result.get('retry_attempts', 0)} retries)" if result.get('retry_attempts', 0) > 0 else ""
        conn_info = f" (conn #{result.get('connection_id', '?')})" if result.get('connection_id') else ""
        print(f"  ❌ Test email FAILED{retry_info}{conn_info} - {result['error_type']}: {result['error']}")
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
    test_index = rate_config["test_index"]
    
    print(f"Starting advanced email campaign to {len(recipients)} recipients...")
    print(f"SMTP accounts: {len(smtp_configs)}")
    print(f"Connection pool: {connection_pool_size} persistent connections")
    print(f"Individual delay: {wait_before_sending}s before each email")
    print(f"Retry attempts: {retry_if_error}")
    print(f"SMTP rotation: Every {rotate_per_smtp} emails")
    print(f"Test email: Every {test_index} emails to {test_recipient}")
    print("=" * 80)
    
    # Initialize SMTP connection pool
    connection_pool = SMTPConnectionPool(smtp_configs, connection_pool_size)
    
    try:
        await connection_pool.initialize()
        
        # Create connection semaphore for limiting concurrent email sends
        connection_semaphore = asyncio.Semaphore(connection_pool_size)
        
        successful_sends = 0
        failed_sends = 0
        test_count = 0
        current_smtp_index = 0
    
        for i, recipient in enumerate(recipients, 1):
            # Send test email every N regular emails (configurable)
            if i % test_index == 0:
                test_count += 1
                test_success = await send_test_email(connection_pool, test_recipient, subject, html_content, test_count, retry_if_error)
                
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
            
            # Display current connection status
            conn_info = f"Pool: {len(connection_pool.connections)} connections"
            print(f"[{i}/{len(recipients)}] Sending to: {recipient} ({conn_info})")
            
            # Apply individual email delay before sending
            if wait_before_sending > 0:
                await asyncio.sleep(wait_before_sending)
            
            # Send email with retry and connection pooling
            result = await send_html_email_with_retry(
                connection_pool=connection_pool,
                to_addr=recipient,
                subject=subject,
                html_content=html_content,
                retry_count=retry_if_error,
                connection_semaphore=connection_semaphore
            )
            
            if result["success"]:
                successful_sends += 1
                retry_info = f" (after {result.get('retry_attempts', 0)} retries)" if result.get('retry_attempts', 0) > 0 else ""
                conn_info = f" (conn #{result.get('connection_id', '?')})" if result.get('connection_id') else ""
                print(f"  ✓ Success{retry_info}{conn_info} - Duration: {result['duration_seconds']:.2f}s")
                
                # Remove successfully sent email from recipients file
                remove_successful_recipient(recipient)
                
                # Log successful email to success tracking file
                save_successful_recipient(recipient)
            else:
                failed_sends += 1
                retry_info = f" (failed after {result.get('retry_attempts', 0)} retries)" if result.get('retry_attempts', 0) > 0 else ""
                conn_info = f" (conn #{result.get('connection_id', '?')})" if result.get('connection_id') else ""
                error_details = f"{result['error_type']}: {result['error']}"
                print(f"  ✗ Failed{retry_info}{conn_info} - {error_details}")
                
                # Log failed email for potential retry later
                save_failed_recipient(recipient, error_details)
            
            # No batch rate limiting - using only individual delays
        
        print("=" * 80)
        print(f"Campaign completed successfully!")
        print(f"Successful sends: {successful_sends} (removed from recipients.txt, logged to send_success.txt)")
        print(f"Failed sends: {failed_sends} (logged to failed_recipients.txt)")
        print(f"Total recipients processed: {len(recipients)}")
        print(f"Test emails sent: {test_count}")
        print(f"SMTP connection pool: {len(connection_pool.connections)} persistent connections")
        
        # Generate statistics
        generate_statistics(connection_pool.smtp_stats, smtp_configs)
        
        # Show remaining recipients count
        try:
            with open("recipients.txt", 'r', encoding='utf-8') as f:
                remaining_count = len([line.strip() for line in f if line.strip()])
            print(f"Remaining recipients in file: {remaining_count}")
        except:
            print("Could not check remaining recipients count")
        
        return True
        
    finally:
        # Always clean up the connection pool
        await connection_pool.close_all()


# Backward compatibility wrapper
async def send_emails_with_rate_limit(smtp_config: SMTPCredentials, recipients: List[str], subject: str, html_content: str, rate_config: dict, test_recipient: str):
    """Legacy wrapper function for backward compatibility."""
    return await send_emails_with_advanced_features([smtp_config], recipients, subject, html_content, rate_config, test_recipient)


# ----------------------------------------------------------------------
# Main function
# ----------------------------------------------------------------------

async def main():
    """Main function to run the email campaign."""
    # Parse command line arguments
    parser = argparse.ArgumentParser(description="SMTP Email Campaign")
    parser.add_argument("--test", action="store_true", help="Run in test mode - only send to addresses in test_recipient.txt")
    args = parser.parse_args()
    
    print("=" * 60)
    if args.test:
        print("SMTP Email Campaign - TEST MODE")
        print("Only sending to addresses in test_recipient.txt")
    else:
        print("SMTP Email Campaign - PRODUCTION MODE")
    print("=" * 60)

    logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")

    try:
        # Load configuration files
        print("Loading configuration files...")
        smtp_configs = load_smtp_config()
        
        # Load recipients based on mode
        if args.test:
            recipients = load_test_recipients_for_campaign()
            print(f"🧪 TEST MODE: Using test recipients from test_recipient.txt")
        else:
            recipients = load_recipients()
            print(f"📧 PRODUCTION MODE: Using recipients from recipients.txt")
        
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
        if args.test:
            print(f"📧 Test mode recipients: {', '.join(recipients)}")
        print(f"Test recipient for connection checks: {test_recipient}")
        print(f"Advanced features:")
        print(f"  - Connection pool: {rate_config['connection']} simultaneous connections")
        print(f"  - Retry attempts: {rate_config['retry_if_error']}")
        print(f"  - Individual delay: {rate_config['wait_before_sending']}s")
        print(f"  - SMTP rotation: Every {rate_config['rotate_per_smtp']} emails")
        print(f"  - Test frequency: Every {rate_config['test_index']} emails")
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
        if not args.test:
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
