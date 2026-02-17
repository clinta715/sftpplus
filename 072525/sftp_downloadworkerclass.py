from PyQt5.QtCore import QRunnable, QObject, pyqtSignal
import enum
import queue
from icecream import ic
import paramiko
import queue
import base64
import re
import os
import time
import threading

def strip_decorative_chars(filename):
    """Strip decorative characters from the filename."""
    # Remove leading emoji characters and spaces
    filename = re.sub(r'^[\U0001F000-\U0001F9FF\s]+', '', filename)
    # Remove any remaining leading or trailing whitespace
    return filename.strip()

class WorkerSignals(QObject):
    progress = pyqtSignal(int, int, float, float)   # transfer_id, percent, speed_bytes_per_sec, eta_seconds
    finished = pyqtSignal(int)
    message  = pyqtSignal(int, str)

MAX_TRANSFERS = 10

response_queues = {}
sftp_queue = queue.Queue()

class SIZE_UNIT(enum.Enum):
    BYTES = 1
    KB = 2
    MB = 3
    GB = 4

class Transfer:
    def __init__(self, transfer_id, progress_bar=None, cancel_button=None, download_worker=None, 
                 active=False, speed_label=None, eta_label=None, status_label=None, 
                 pause_button=None, list_item=None):
        self.transfer_id = transfer_id
        self.progress_bar = progress_bar
        self.cancel_button = cancel_button
        self.download_worker = download_worker
        self.active = active
        self.speed_label = speed_label
        self.eta_label = eta_label
        self.status_label = status_label
        self.pause_button = pause_button
        self.list_item = list_item
        self.paused = False
        self.layout = None  # Initialize layout attribute

class transferSignals(QObject):
    showhide = pyqtSignal()

class QueueItem:
    def __init__(self, name, id):
        self.name = name
        self.id = id

class SFTPJob:
    def __init__(self, source_path, is_source_remote, destination_path, is_destination_remote, hostname, username, password, port, command, id, key ):
        self.source_path = source_path
        self.is_source_remote = is_source_remote
        self.destination_path = destination_path
        self.is_destination_remote = is_destination_remote
        self.hostname = hostname
        self.username = username
        self.password = password
        self.port = port
        self.command = command
        self.id = id
        self.key = key

    def to_dict(self):
        return {
            "source_path": self.source_path,
            "is_source_remote": self.is_source_remote,
            "destination_path": self.destination_path,
            "is_destination_remote": self.is_destination_remote,
            "hostname": self.hostname,
            "username": self.username,
            "password": base64.b64encode(self.password.encode()).decode(),  # Encode password
            "port": self.port,
            "command": self.command,
            "id": self.id,
            "key" : self.key
        }

    @staticmethod
    def from_dict(data):
        data["password"] = base64.b64decode(data["password"]).decode()  # Decode password
        return SFTPJob(**data)

def clear_sftp_queue():
    while True:
        try: 
            sftp_queue.get_nowait()
        except:
            break

def add_sftp_job(source_path, is_source_remote, destination_path, is_destination_remote, hostname, username, password, port, command, id, key ):
    job = SFTPJob(
        source_path, is_source_remote, destination_path, is_destination_remote,
        hostname, username, password, port, command, id, key )
    sftp_queue_put(job)

def sftp_queue_get():
    return(sftp_queue.get_nowait())

def sftp_queue_put(job):
    sftp_queue.put(job)

def sftp_queue_isempty():
    return sftp_queue.empty()

def delete_response_queue(job_id):
    if job_id in response_queues:
        del response_queues[job_id]

def create_response_queue(job_id):
    # Create a new queue
    new_queue = queue.Queue()
    # Assign the new queue to the specified job_id in response_queues
    response_queues[job_id] = new_queue
    # Return the newly created queue
    return new_queue

def check_response_queue(job_id):
    try:
        # Try to get an item from the queue without blocking
        item = response_queues[job_id].get_nowait()
        return item
    except queue.Empty:
        # If the queue is empty, return None
        return None

class DownloadWorker(QRunnable):
    def __init__(self, transfer_id, job_source, job_destination, is_source_remote, is_destination_remote, hostname, port, username, password, command=None, key=None):
        super(DownloadWorker, self).__init__()
        self.transfer_id = transfer_id
        self._stop_flag = False
        self.signals = WorkerSignals()
        # self.connection_pool = ConnectionPool()
        # self.ssh = self.connection_pool.get_connection(hostname, port, username, password)
        self.is_source_remote = is_source_remote
        self.job_source = job_source
        self.job_destination = job_destination
        self.is_destination_remote = is_destination_remote
        self.hostname = hostname
        self.port = port
        self.username = username
        self.password = password
        self.command = command

        if key == "<none>":
            self.key = None
        else:
            self.key = key
            # this should be the FILENAME

        self._last_bytes = 0
        self._last_time  = None

        try:
            self.ssh = paramiko.SSHClient()
            self.ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())

            if self.key: # if there is a key file specified
                try: # try to load the key from the file
                    self.temp_key = self._load_private_key(self.key)
                except Exception as e:
                    ic(e)
                    self.signals.message.emit(self.transfer_id,f"Error : {e}.")
            else:
                self.temp_key=None # if not make sure the variable exists and is set to None
            
            self.ssh.connect(self.hostname, self.port, self.username, self.password, timeout=60,pkey=self.temp_key)
            self.transport = self.ssh.get_transport()
            self.transport.set_keepalive(20)
        except Exception as e:
            self.signals.message.emit(self.transfer_id,f"Connection to {hostname} failed.")
            self.signals.message.emit(self.transfer_id,f"Error : {e}.")
            ic(e)

    def convert_unit(self, size_in_bytes: int, unit: SIZE_UNIT):
        # """Convert the size from bytes to
        # other units like KB, MB or GB
        # """
        if unit == SIZE_UNIT.KB:
            return size_in_bytes/1024
        elif unit == SIZE_UNIT.MB:
            return size_in_bytes/(1024*1024)
        elif unit == SIZE_UNIT.GB:
            return size_in_bytes/(1024*1024*1024)
        else:
            return size_in_bytes

    def progress(self, transferred: int, total: int):
        if self._stop_flag:
            raise Exception("Transfer interrupted")

        # ---- compute speed & eta ----
        now = time.time()
        if self._last_time is None:
            speed_bps = 0.0
            eta_sec   = 0.0
        else:
            delta_t   = now - self._last_time
            delta_b   = transferred - self._last_bytes
            speed_bps = delta_b / max(delta_t, 1e-6)
            eta_sec   = (total - transferred) / max(speed_bps, 1e-6)

        self._last_bytes = transferred
        self._last_time  = now

        percent = int(transferred * 100 / total)
        self.signals.progress.emit(self.transfer_id, percent, speed_bps, eta_sec)

    # helper used by both get and put
    def _transfer_with_timeout(self, transfer_func, *args):
        """
        transfer_func : either sftp.get or sftp.put
        *args         : (remote_path, local_path, callback=progress)
        """
        watchdog_lock = threading.Lock()
        watchdog_time = [time.time()]       # mutable container for closure

        def watchdog():
            while True:
                time.sleep(5)               # coarse tick is enough
                with watchdog_lock:
                    if time.time() - watchdog_time[0] > 60:
                        # no progress for 60 s → nuke the channel
                        self.signals.message.emit(
                            self.transfer_id,
                            "watchdog closing"
                        )
                        try:
                            self.sftp.close()
                            self.ssh.close()
                            self.signals.finished.emit(self.transfer_id)
                        except:
                            pass

                        break

        def progress_wrapper(transferred, total):
            with watchdog_lock:
                watchdog_time[0] = time.time()
            # forward to original callback
            self.progress(transferred, total)

        wd_thread = threading.Thread(target=watchdog, daemon=True)
        wd_thread.start()

        try:
            transfer_func(*args[:2], callback=progress_wrapper)
        except Exception as exc:            # socket/SSH errors after sftp.close()
            self.signals.message.emit(
                self.transfer_id,
                f"Transfer {self.transfer_id} was interrupted: {exc}"
            )
        finally:
            self.signals.finished.emit(self.transfer_id)
            self.sftp.close()
            self.ssh.close()
            # watchdog will exit because of daemon=True or because we closed sftp

    def run(self):
        try:

            self.sftp = self.ssh.open_sftp()
        except Exception as e:
            self.signals.message.emit(self.transfer_id,f"download_thread() {e}")
            return

        # Strip decorative characters from source and destination paths
        clean_source = strip_decorative_chars(self.job_source)
        clean_destination = strip_decorative_chars(self.job_destination)

        if self.is_source_remote and not self.is_destination_remote:
            self.signals.message.emit(
                self.transfer_id,
                f"download_thread() {clean_source} → {clean_destination}"
            )
            self._transfer_with_timeout(self.sftp.get, clean_source, clean_destination)

        elif self.is_destination_remote and not self.is_source_remote:
            self.signals.message.emit(
                self.transfer_id,
                f"upload_thread() {clean_source} → {clean_destination}"
            )
            self._transfer_with_timeout(self.sftp.put, clean_source, clean_destination)

        elif self.is_source_remote and self.is_destination_remote:
            # must be a mkdir
            try:
                if self.command == "mkdir":
                    try:
                        self.sftp.mkdir(self.job_destination)
                        response_queues[self.transfer_id].put("success")
                        response_queues[self.transfer_id].put(self.job_destination)

                    except Exception as e:
                        response_queues[self.transfer_id].put("error")
                        response_queues[self.transfer_id].put(e)
                        # ic(e)

                elif self.command == "listdir_attr":
                    try:
                        response = self.sftp.listdir_attr(self.job_source)
                        response_queues[self.transfer_id].put("success")
                        response_queues[self.transfer_id].put(response)

                    except Exception as e:
                        response_queues[self.transfer_id].put("error")
                        response_queues[self.transfer_id].put(e)
                        # ic(e)

                elif self.command == "listdir":
                    try:
                        response = self.sftp.listdir(self.job_source)
                        response_queues[self.transfer_id].put("success")
                        response_queues[self.transfer_id].put(response)

                    except Exception as e:
                        response_queues[self.transfer_id].put("error")
                        response_queues[self.transfer_id].put(e)
                        ic(e)

                elif self.command == "chdir":
                    try:
                        self.sftp.chdir(self.job_source)
                        response_queues[self.transfer_id].put("success")
                        response_queues[self.transfer_id].put(self.job_source)

                    except Exception as e:
                        response_queues[self.transfer_id].put("error")
                        response_queues[self.transfer_id].put(e)
                        # ic(e)

                elif self.command == "rmdir":
                    try:
                        self.sftp.rmdir(self.job_source)
                        response_queues[self.transfer_id].put("success")
                        response_queues[self.transfer_id].put(self.job_source)

                    except Exception as e:
                        response_queues[self.transfer_id].put("error")
                        response_queues[self.transfer_id].put(e)
                        # ic(e)

                elif self.command == "stat":
                    try:
                        attr = self.sftp.stat(self.job_source)
                        response_queues[self.transfer_id].put("success")
                        response_queues[self.transfer_id].put(attr)

                    except Exception as e:
                        response_queues[self.transfer_id].put("error")
                        response_queues[self.transfer_id].put(e)
                        # ic(e)

                elif self.command == "remove":
                    try:
                        self.sftp.remove(self.job_source)
                        response_queues[self.transfer_id].put("success")
                        response_queues[self.transfer_id].put(self.job_source)

                    except Exception as e:
                        response_queues[self.transfer_id].put("error")
                        response_queues[self.transfer_id].put(e)
                        # ic(e)

                elif self.command == "getcwd":
                    try:
                        stdin, stdout, stderr = self.ssh.exec_command('cd {}'.format(self.job_source))
                        stdin, stdout, stderr = self.ssh.exec_command('pwd')
                        if stderr.read():
                            ic("Error:", stderr.read().decode())
                            pass
                        getcwd_path = stdout.read().strip().decode()
                        # .replace("\\", "/")
                        response_queues[self.transfer_id].put("success")
                        response_queues[self.transfer_id].put(getcwd_path)

                    except Exception as e:
                        response_queues[self.transfer_id].put("error")
                        response_queues[self.transfer_id].put(e)
                        ic(e)

            except Exception as e:
                self.signals.message.emit(self.transfer_id, f"{self.command} operation failed: {e}")
                response_queues[self.transfer_id].put("error")
                response_queues[self.transfer_id].put(e)

            finally:
                self.sftp.close()
                self.ssh.close()
                self.signals.finished.emit(self.transfer_id)

    def stop_transfer(self):
        self._stop_flag = True
        self.signals.message.emit(self.transfer_id, f"Transfer {self.transfer_id} ends.")
