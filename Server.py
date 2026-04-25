# Implements a simple HTTP Server
import mimetypes
import os
import socket
import threading
from datetime import datetime, timezone
from queue import Empty, Queue

def handle_log_file(log_queue, stop_event):
    log_file_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'log.txt')
    while (not stop_event.is_set()) or (not log_queue.empty()):
        try:
            log_data = log_queue.get(timeout = 1)
            with open(log_file_path, "a") as append_file:
                append_file.write(str(log_data[0]) + " " + str(log_data[1].strftime("%a, %d %b %Y %H:%M:%S GMT")) + " " + str(log_data[2]) + " " + str(log_data[3]) + "\n")
        except Empty:
            continue

def standard_response(
    client_address,
    log_queue,
    access_time,
    filename,
    status_code,
    content_type = None,
    content = None,
    last_modified = None,
    is_Head = False
    ):
    if status_code == 200:
        reason_phrase = "OK"
    elif status_code == 304:
        reason_phrase = "Not Modified"
    elif status_code == 400:
        reason_phrase = "Bad Request"
        content_type = "text/plain"
        content = b"Request Not Supported"
    elif status_code == 403:
        reason_phrase = "Forbidden"
        content_type = "text/plain"
        content = b"Forbidden: Access denied"
    elif status_code == 404:
        reason_phrase = "Not Found"
        content_type = "text/plain"
        content = b"File Not Found"
    log_queue.put((client_address[0], access_time, filename, str(status_code) + " " + reason_phrase))
    response = (
        "HTTP/1.1 " + str(status_code) + " " + reason_phrase + "\r\n" +
        (("Content-Type: " + content_type + "\r\n") if status_code != 304 else "") +
        (("Last-Modified: " + datetime.fromtimestamp(last_modified, timezone.utc).strftime("%a, %d %b %Y %H:%M:%S GMT") + "\r\n") if status_code == 200 else "") +
        "Content-Length: " + str(0 if content == None else len(content)) + "\r\n" +
        "\r\n"
        ).encode() + (b"" if is_Head or status_code == 304 else content)
    print("response: \n" + response.decode())
    return response

# Handle the HTTP request.
def handle_request(client_connection, client_address, log_queue, stop_event):
    is_keep_alive = True
    while is_keep_alive and (not stop_event.is_set()):
        # Get the client request
        request = b""
        client_connection.settimeout(1)
        while (b"\r\n\r\n" not in request) and (not stop_event.is_set()):
            try:
                request += client_connection.recv(1024)
            except socket.timeout:
                pass
        if stop_event.is_set() and (b"\r\n\r\n" not in request):
            continue
        access_time = datetime.now(timezone.utc)
        try:
            request = request.decode()
            print('request:\n', request)

            # Parse HTTP headers
            headers = request.split('\r\n')
            fields = headers[0].split()
            request_type = fields[0]
            filename = fields[1]
            if fields[2].split("/")[1] == "1.0":
                is_keep_alive = False
            elif fields[2].split("/")[1] == "1.1":
                is_keep_alive = True
            else:
                raise Exception("Unknow HTTP version")
            browser_time = None
            for line in headers:
                if "Connection".lower() in line.lower():
                    if line.split(":", 1)[1].lower().strip() == "close":
                        is_keep_alive = False
                    elif line.split(":", 1)[1].lower().strip() == "keep-alive":
                        is_keep_alive = True
                if "If-Modified-Since".lower() in line.lower():
                    try:
                        browser_time = datetime.strptime(
                            line.split(":", 1)[1].strip(),
                            "%a, %d %b %Y %H:%M:%S GMT"
                            ).replace(tzinfo = timezone.utc).timestamp()
                    except Exception:
                        pass

        except Exception:
            response = standard_response(client_address, log_queue, access_time, "N/A", 400)
            client_connection.sendall(response)
            is_keep_alive = False
            continue

        # Parse the request type
        if request_type in ['GET', 'HEAD']:
            # Get the content of the file
            if filename == '/':
                filename = 'index.html'
            else:
                filename = filename[1:]
            file_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'htdocs', filename)

            if not os.path.commonpath([os.path.realpath(file_path), os.path.join(os.path.dirname(os.path.abspath(__file__)), 'htdocs')]) == os.path.join(os.path.dirname(os.path.abspath(__file__)), 'htdocs'):
                response = standard_response(client_address, log_queue, access_time, filename, 403)
                client_connection.sendall(response)
                continue

            if not os.path.exists(file_path):
                response = standard_response(client_address, log_queue, access_time, filename, 404)
                client_connection.sendall(response)
                continue

            if browser_time and int(os.path.getmtime(file_path)) <= int(browser_time):
                response = standard_response(client_address, log_queue, access_time, filename, 304)
                client_connection.sendall(response)
                continue

            file_type = "application/octet-stream" if mimetypes.guess_type(file_path)[0] == None else mimetypes.guess_type(file_path)[0]

            with open(file_path, 'rb') as read_file:
                file_content = read_file.read()
            response = standard_response(client_address, log_queue, access_time, filename, 200, file_type, file_content, os.path.getmtime(file_path), request_type == 'HEAD')
            client_connection.sendall(response)
        else:
            response = standard_response(client_address, log_queue, access_time, "N/A", 400)
            client_connection.sendall(response)
            is_keep_alive = False
            continue
    client_connection.close()

# Define socket host
SERVER_HOST = '127.0.0.1'
SERVER_PORT = 8000

# Create socket
server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
try:
    server_socket.bind((SERVER_HOST, SERVER_PORT))
except:
    server_socket.bind((SERVER_HOST, 0))
server_socket.listen()
SERVER_PORT = server_socket.getsockname()[1]

# Create index.html
index_web_code = """<!DOCTYPE html>
<html>
    <head>
        <meta charset="UTF-8">
        <link rel="icon" href="data:,">
        <title>Index</title>
    </head>

    <body>
        <h1>Welcome to the index.html web page.</h1>
    </body>
</html>
"""

os.makedirs(os.path.join(os.path.dirname(os.path.abspath(__file__)), 'htdocs'), exist_ok=True)
with open(os.path.join(os.path.dirname(os.path.abspath(__file__)), 'htdocs', 'index.html'), 'w') as f:
    f.write(index_web_code)

stop_event = threading.Event()

log_queue = Queue()
# Create log_queue thread
thread = threading.Thread(
    target = handle_log_file,
    args = (log_queue, stop_event,)
    )
thread.start()

server_socket.settimeout(1)

print('Listening on port ', SERVER_PORT,' ...')
try:
    while True:
        try:
            # Wait for client connections
            client_connection, client_address = server_socket.accept()

            # Create a new thread
            thread = threading.Thread(
                target = handle_request,
                args = (client_connection, client_address, log_queue, stop_event,)
                )

            thread.start()
        except socket.timeout:
            continue
except KeyboardInterrupt:
    # Close socket
    server_socket.close()
    # Close thread
    stop_event.set()