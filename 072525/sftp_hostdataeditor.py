import sys
import os
from PyQt5.QtWidgets import (
    QApplication, QWidget, QPushButton, QVBoxLayout,
    QTableWidget, QTableWidgetItem, QMessageBox, QHeaderView
)
from PyQt5.QtCore import Qt
import json
from cryptography.fernet import Fernet
from PyQt5.QtWidgets import QDialog  # Make sure to import QDialog
from icecream import ic

encryption_key = []
cipher_suite = []

def save_connection_data(host_data):
    global encryption_key, cipher_suite
    try:
        # Ensure the data structure is complete
        if not all(key in host_data for key in ["hostnames", "usernames", "passwords", "ports", "key"]):
            raise ValueError("Incomplete host data structure")

        # Encrypt passwords
        encrypted_passwords = {k: cipher_suite.encrypt(v.encode()).decode() 
                             for k, v in host_data["passwords"].items()}

        data = {
            "hostnames": host_data["hostnames"],
            "usernames": host_data["usernames"],
            "passwords": encrypted_passwords,
            "ports": host_data["ports"],
            "key" : host_data["key"],
            "encryption_key": encryption_key.decode() if isinstance(encryption_key, bytes) else encryption_key
        }

        # Save to file with proper error handling
        with open('connection_data.json', 'w') as f:
            json.dump(data, f, indent=4)  # Add indentation for better readability
        return True
    except Exception as e:
        ic(e)
        return False

def load_connection_data():
    global encryption_key, cipher_suite
    host_data = {"hostnames": {}, "usernames": {}, "passwords": {}, "ports": {}, "key": {}}

    try:
        # Check if file exists and is readable
        if not os.path.exists('connection_data.json'):
            raise FileNotFoundError("Connection data file not found")

        with open('connection_data.json', 'r') as f:
            data = json.load(f)

        # Validate encryption key
        encryption_key = data.get("encryption_key", Fernet.generate_key())
        if not isinstance(encryption_key, (str, bytes)):
            raise ValueError("Invalid encryption key format")
            
        cipher_suite = Fernet(encryption_key)

        # Load and validate data
        host_data["hostnames"] = data.get("hostnames", {})
        host_data["usernames"] = data.get("usernames", {})
        
        # Decrypt passwords with error handling
        encrypted_passwords = data.get("passwords", {})
        host_data["passwords"] = {}
        for k, v in encrypted_passwords.items():
            try:
                host_data["passwords"][k] = cipher_suite.decrypt(v.encode()).decode()
            except Exception as e:
                print(f"Error decrypting password for {k}: {str(e)}")
                host_data["passwords"][k] = ""  # Set empty password if decryption fails
                
        host_data["ports"] = data.get("ports", {})
        host_data["key"] = data.get("key",{})

        return host_data

    except FileNotFoundError:
        # If the file doesn't exist, generate a new encryption key
        encryption_key = Fernet.generate_key()
        cipher_suite = Fernet(encryption_key)
        return host_data
        
    except json.JSONDecodeError:
        print("Error: Invalid JSON format in connection data file")
        encryption_key = Fernet.generate_key()
        cipher_suite = Fernet(encryption_key)
        return host_data
        
    except Exception as e:
        print(f"Error loading connection data: {str(e)}")
        encryption_key = Fernet.generate_key()
        cipher_suite = Fernet(encryption_key)
        return host_data

class HostDataEditor(QDialog):  # Change QWidget to QDialog
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Host Data Editor")
        self.resize(800, 600)  # Set an initial window size

        self.table = QTableWidget()
        self.table.setColumnCount(5)
        self.table.setHorizontalHeaderLabels(["Hostname", "Username", "Password", "Port", "Key"])
        
        # Set the horizontal header to resize based on content
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setStretchLastSection(True)  # Ensure last section takes up remaining space

        # You can also set the vertical header to resize based on content if needed
        self.table.verticalHeader().setSectionResizeMode(QHeaderView.ResizeToContents)

        self.add_button = QPushButton("Add Row")
        self.add_button.clicked.connect(self.add_row)

        self.delete_button = QPushButton("Delete Selected Row")
        self.delete_button.clicked.connect(self.delete_row)

        self.save_button = QPushButton("Save")
        self.save_button.clicked.connect(self.save_data)

        layout = QVBoxLayout()
        layout.addWidget(self.table)
        layout.addWidget(self.add_button)
        layout.addWidget(self.delete_button)
        layout.addWidget(self.save_button)
        self.setLayout(layout)

        # Initialize host_data before loading data
        self.host_data = {"hostnames": {}, "usernames": {}, "passwords": {}, "ports": {}, "key":{}}
        
        # Load the data
        self.host_data = self.load_data()
        self.update_table()

    def load_data(self):
        try:
            data = load_connection_data()
            self.update_table()
            return data
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Failed to load data: {str(e)}")

    def add_row(self):
        row_count = self.table.rowCount()
        self.table.insertRow(row_count)

    def delete_row(self):
        selected_row = self.table.currentRow()
        if selected_row >= 0:
            hostname_item = self.table.item(selected_row, 0)
            if hostname_item:
                hostname = hostname_item.text()
                # Remove the corresponding data from host_data
                self.host_data["hostnames"].pop(hostname, None)
                self.host_data["usernames"].pop(hostname, None)
                self.host_data["passwords"].pop(hostname, None)
                self.host_data["ports"].pop(hostname, None)
                self.host_data["key"].pop(hostname, None)
            self.table.removeRow(selected_row)
        else:
            QMessageBox.warning(self, "No selection", "Please select a row to delete.")

    def save_data(self):
        try:
            # Collect data from the table before saving
            for i in range(self.table.rowCount()):
                hostname_item = self.table.item(i, 0)
                username_item = self.table.item(i, 1)
                password_item = self.table.item(i, 2)
                port_item = self.table.item(i, 3)
                key_item = self.table.item(i, 4)

                if not all([hostname_item, username_item, password_item, port_item]):
                    raise ValueError("All fields must be filled out.")

                hostname = hostname_item.text()
                username = username_item.text()
                password = password_item.text()
                port = int(port_item.text())
                key = key_item.text()
                # Update host_data dictionary
                self.host_data["hostnames"][hostname] = hostname
                self.host_data["usernames"][hostname] = username
                self.host_data["passwords"][hostname] = password  # Will be encrypted on save
                self.host_data["ports"][hostname] = port
                self.host_data["key"][hostname] = key

            # Save the data using the parent's save function
            save_connection_data(self.host_data)
            # QMessageBox.information(self, "Success", "Data saved successfully.")
        except ValueError as e:
            QMessageBox.critical(self, "Error", str(e))
        except Exception as e:
            QMessageBox.critical(self, "Unknown Error", f"An error occurred: {str(e)}")

    def update_table(self):
        self.table.setRowCount(len(self.host_data["hostnames"]))
        for i, hostname in enumerate(self.host_data["hostnames"]):
            self.table.setItem(i, 0, QTableWidgetItem(hostname))
            self.table.setItem(i, 1, QTableWidgetItem(self.host_data["usernames"][hostname]))
            self.table.setItem(i, 2, QTableWidgetItem(self.host_data["passwords"][hostname]))  # Decrypted password
            self.table.setItem(i, 3, QTableWidgetItem(str(self.host_data["ports"][hostname])))
            self.table.setItem(i, 4, QTableWidgetItem(self.host_data["ports"][hostname]))
            self.table.setItem(i, 5, QTableWidgetItem(self.host_data["key"][hostname]))

    def closeEvent(self, event):
        # Save data when the window is closed
        try:
            self.save_data()  # Call save_data() to collect and save the data
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Failed to save data on close: {str(e)}")
        event.accept()  # Accept the close event
