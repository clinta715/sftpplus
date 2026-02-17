from flask import Flask, request, jsonify
import os
import subprocess

app = Flask(__name__)

@app.route('/execute', methods=['POST'])
def execute_command():
    command = request.form.get('command')

    if command == 'list_lock_files':
        lock_files = [f for f in os.listdir('/tmp') if f.endswith('.lock')]
        return jsonify(lock_files)

    elif command == 'list_log_files':
        log_files = [f for f in os.listdir('/tmp') if f.endswith('.log') and f.startswith(('resyncz', 'iterate', 'testz', 'remote', 'tapez'))]
        return jsonify(log_files)

    elif command.startswith('show_log_content:'):
        log_file = command.split(':')[-1]
        log_path = os.path.join('/tmp', log_file)
        if os.path.exists(log_path):
            with open(log_path, 'r') as file:
                content = file.read()
            return content
        else:
            return f"Log file '{log_file}' not found."

    elif command == 'show_crontab':
        crontab = subprocess.check_output(['crontab', '-l'], universal_newlines=True)
        return crontab

    else:
        return 'Invalid command.'

if __name__ == '__main__':
    app.run(port=8080)  # Change the port as needed
