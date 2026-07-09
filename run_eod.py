import os
import sys
import logging

logging.basicConfig(level=logging.INFO)

# Load environment variables
from dotenv import load_dotenv
load_dotenv()

from engine.eod_scanner import EODScanner

if __name__ == "__main__":
    scanner = EODScanner()
    scanner.run()
