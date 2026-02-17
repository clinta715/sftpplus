import sys
import argparse
from datetime import datetime, timedelta
from http.server import HTTPServer, BaseHTTPRequestHandler
import json
from threading import Thread
import time
from typing import Dict, List
import os

# Global variables
job_status: Dict[str, Dict[str, bool]] = {}  # {date: {job: status}}
jobs: List[str] = []
days: int = 0
save_interval = 300  # 5 minutes
save_file = "job_status.json"

class RequestHandler(BaseHTTPRequestHandler):
    def do_POST(self):
        content_length = int(self.headers['Content-Length'])
        post_data = self.rfile.read(content_length)

        try:
            data = json.loads(post_data.decode('utf-8'))
            job = data.get('job')
            status = data.get('status', False)
            date = data.get('date', datetime.now().strftime('%Y-%m-%d'))

            if date in job_status and job in job_status[date]:
                job_status[date][job] = status
                self.send_response(200)
                self.end_headers()
                self.wfile.write(b'Status updated')
                # Save immediately on update
                save_status()
                # Redraw the grid
                print_grid()
            else:
                self.send_response(400)
                self.end_headers()
                self.wfile.write(b'Invalid job or date')
        except Exception as e:
            self.send_response(500)
            self.end_headers()
            self.wfile.write(str(e).encode())

def start_server(port=1337):
    server = HTTPServer(('localhost', port), RequestHandler)
    print(f"Server started on port {port}")
    server.serve_forever()

def save_status():
    with open(save_file, 'w') as f:
        json.dump(job_status, f)

def load_status():
    global job_status
    try:
        with open(save_file, 'r') as f:
            job_status = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        job_status = {}

def init_status(jobs: List[str], days: int):
    global job_status
    today = datetime.now()

    for i in range(days):
        date_str = (today + timedelta(days=i)).strftime('%Y-%m-%d')
        if date_str not in job_status:
            job_status[date_str] = {job: False for job in jobs}

def print_grid():
    os.system('cls' if os.name == 'nt' else 'clear')  # Clear screen

    # Get current date
    today = datetime.now()

    # Calculate column widths
    date_col_width = 12
    terminal_width = 80  # Default, will try to get actual width
    try:
        import shutil
        terminal_width = shutil.get_terminal_size().columns
    except:
        pass

    available_width = terminal_width - date_col_width - 1
    job_col_width = max(6, available_width // len(jobs))

    # Print header (job names)
    print(" " * (date_col_width + 1) + "|", end="")
    for job in jobs:
        truncated_job = job[:job_col_width-1]
        print(truncated_job.center(job_col_width), end="")
    print()

    # Print separator line
    print("-" * terminal_width)

    # Print each day's row
    for day in range(days):
        date = today + timedelta(days=day)
        date_str = date.strftime('%Y-%m-%d')

        # Print date
        print(date.strftime('%Y-%m-%d'), end="")

        # Print job statuses for this date
        print(" |", end="")
        for job in jobs:
            status = job_status.get(date_str, {}).get(job, False)

            # Display job status
            if status:
                print("[DONE]".center(job_col_width), end="")
            else:
                print("[    ]".center(job_col_width), end="")
        print()

    # Add instructions at the bottom
    print("\nPress Ctrl+C to quit")
    print(f"Send POST requests to http://localhost:1337 to update status")

def main():
    global jobs, days

    args = parse_args()
    jobs = args.jobs.split(',')
    days = args.days

    # Load existing status
    load_status()

    # Initialize status if not loaded from file
    if not job_status:
        init_status(jobs, days)

    # Start HTTP server in a separate thread
    server_thread = Thread(target=start_server)
    server_thread.daemon = True
    server_thread.start()

    # Start save thread
    def save_periodically():
        while True:
            time.sleep(save_interval)
            save_status()

    save_thread = Thread(target=save_periodically)
    save_thread.daemon = True
    save_thread.start()

    # Initial grid display
    print_grid()

    try:
        # Simple input loop to keep program running
        while True:
            # Check for updates every second
            time.sleep(1)
    except KeyboardInterrupt:
        pass
    finally:
        # Save before exiting
        save_status()
        print("\nApplication exited. Status saved.")

def parse_args():
    parser = argparse.ArgumentParser(description='Job Status Grid')
    parser.add_argument('--jobs', required=True, help='Comma-separated list of job names')
    parser.add_argument('--days', type=int, required=True, help='Number of days to display')
    return parser.parse_args()

if __name__ == "__main__":
    main()
