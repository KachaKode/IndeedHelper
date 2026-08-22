#https://chatgpt.com/c/415d0f38-edd3-4985-876a-e4c3bc75cb48

import requests
import smtplib
from email.mime.text import MIMEText




class TxtMessager:

    def configEmail(self):
        # Email settings
        self.smtp_server = 'smtp.gmail.com'  # Use your email provider's SMTP server
        self.smtp_port = 587  # For TLS
        self.smtp_user = 'Tommy@IvyKode.com'  # Your email address
        self.smtp_password = 'your-email-password'  # Your email password

    def configGateway(self):
        # SMS gateway settings for H2O Wireless
        phone_number = '1234567890'  # Replace with your 10-digit phone number
        sms_gateway = f'{phone_number}@txt.att.net'

    def configMsg(self):
        # Message content
        subject = 'Test'
        body = 'This is a test message.'

        # Create the email message
        msg = MIMEText(body)
        msg['From'] = smtp_user
        msg['To'] = sms_gateway
        msg['Subject'] = subject

    def executeMsg(self):
        try:
            # Connect to the SMTP server
            server = smtplib.SMTP(smtp_server, smtp_port)
            server.starttls()  # Upgrade the connection to secure
            server.login(smtp_user, smtp_password)

            # Send the message
            server.sendmail(smtp_user, sms_gateway, msg.as_string())
            print('Message sent successfully!')

        except Exception as e:
            print(f'Failed to send message: {e}')

        finally:
            server.quit()

    def send(self):
        self.configEmail()

        self.configGateway()

        self.configMsg()

        self.executeMsg()

    def lookup_carrier(self, phone_number):
        url = 'https://freecarrierlookup.com/api/v1/'
        params = {
            'number': phone_number,
            'country': 'US'  # Assuming the phone number is from the US. Adjust as needed.
        }

        try:
            response = requests.get(url, params=params)
            response.raise_for_status()  # Raise an error for bad responses
            data = response.json()
            return data
        except requests.RequestException as e:
            return f'Error: {e}'
        except ValueError:
            return 'Error: Invalid response from Free Carrier Lookup API.'
    pass


if __name__ == "__main__":
    msger = TxtMessager("7703835362", "att")