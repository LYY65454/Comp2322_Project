# Implements a simple HTTP Server
# Import required library
import mimetypes
import os
import socket
import threading
from datetime import datetime, timezone
from queue import Empty, Queue

# Dedicated a thread for writing server logs to log file to avoid race conditions in multi-threaded environment
def handle_log_file(log_queue, stop_event):

    log_file_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'log.txt') # Define log file path

    while (not stop_event.is_set()) or (not log_queue.empty()): # The thread only terminates when stop event is triggered and queue is empty

        try:
            log_data = log_queue.get(timeout = 1) # Prevent the thread from being blocked indefinitely and unable to terminate

            with open(log_file_path, "a") as append_file:
                append_file.write(str(log_data[0]) + " " + str(log_data[1].strftime("%a, %d %b %Y %H:%M:%S GMT")) + " " + str(log_data[2]) + " " + str(log_data[3]) + "\n") # Add a line of record in the log

        except Empty: # Handle Empty exception
            pass

# Handle a HTTP response
def standard_response(
    client_connection,
    client_address,
    log_queue,
    is_keep_alive,
    access_time,
    filename,
    status_code,
    content_type = None,
    content = None,
    last_modified = None,
    is_Head = False
    ):

    # Automatically assign response fields according to status code
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

    log_queue.put((client_address[0], access_time, filename, str(status_code) + " " + reason_phrase)) # Push request metadata into log_queue

    head_response = (
        "HTTP/1.1 " + str(status_code) + " " + reason_phrase + "\r\n" +
        (("Content-Type: " + content_type + "\r\n") if status_code != 304 else "") +
        (("Last-Modified: " + datetime.fromtimestamp(last_modified, timezone.utc).strftime("%a, %d %b %Y %H:%M:%S GMT") + "\r\n") if status_code == 200 else "") +
        "Content-Length: " + str(0 if content == None else len(content)) + "\r\n" +
        "\r\n"
        ).encode() # build a response byte stream

    body_response = (b"" if is_Head or status_code == 304 else content)

    print(threading.current_thread().name + " response: \n" + (head_response).decode()) # Debug output
    print("Connection: " + ("keep alive" if is_keep_alive else "close"))

    client_connection.sendall(head_response + body_response) # Send response back to client

# Handle the HTTP request
def handle_request(client_connection, client_address, log_queue, stop_event):

    is_keep_alive = True # define a flag to control the loop

    while is_keep_alive and (not stop_event.is_set()): # The thread terminates when stop event is triggered or the client/server decides to close the connection

        # Get the client request
        request = b""

        client_connection.settimeout(1) # Prevent the thread from being blocked indefinitely and unable to terminate

        # Read full HTTP header until "\r\n\r\n"
        while (b"\r\n\r\n" not in request) and (not stop_event.is_set()): # The loop stops when stop event is triggered or the full HTTP request header has been received

            try:
                request += client_connection.recv(1024)

            except socket.timeout: # Handle Empty exception
                pass

        access_time = datetime.now(timezone.utc) # Get the current UTC timestamp

        if stop_event.is_set() and (b"\r\n\r\n" not in request): # Skip incomplete request if server is shutting down
            continue
        
        valid_http_header = True # Indicates whether the received HTTP request header is valid

        try:

            request = request.decode() # Decode the raw HTTP request
            print('request:\n', request) # Debug output

            # Parse HTTP headers
            headers = request.split('\r\n')
            fields = headers[0].split()

            # Handle HTTP Method
            if fields[0] == 'GET':
                is_head = False

            elif fields[0] == 'HEAD':
                is_head = True

            else:
                raise Exception("Unknow HTTP method") # Handle Unknow input

            # Get the content of the file
            if fields[1] == '/':
                filename = 'index.html' # default

            elif fields[1][0] == '/':
                filename = fields[1][1:] # remove leading "/" from URL path

            else:
                raise Exception("Invalid HTTP request format") # Handle Unknow input

            if "HTTP/1.0" == fields[2]:
                is_keep_alive = False # close connection after response

            elif "HTTP/1.1" == fields[2]:
                is_keep_alive = True # Keep TCP connection

            else:
                raise Exception("Unknow HTTP version") # Handle Unknow input

        except Exception:
            valid_http_header = False # Mark as invalid if any error occurs during HTTP header parsing

        browser_time = None

        for line in headers:

            # Handle Connection header
            if "Connection".lower() in line.lower():

                if "close" in line.split(":", 1)[1].lower():
                    is_keep_alive = False # close connection after response

                elif "keep-alive" in line.split(":", 1)[1].lower():
                    is_keep_alive = True # Keep TCP connection

            if "If-Modified-Since".lower() in line.lower():

                try:

                    # Parse browser's cached timestamp (RFC 1123 format)
                    browser_time = datetime.strptime(
                        line.split(":", 1)[1].strip(),
                        "%a, %d %b %Y %H:%M:%S GMT"
                        ).replace(tzinfo = timezone.utc).timestamp()

                except Exception:
                    pass # Ignore invalid date format

        # If HTTP request parsing failed, return 400
        if not valid_http_header:
            standard_response(client_connection, client_address, log_queue, is_keep_alive, access_time, "N/A", 400)
            is_keep_alive = False # close connection

        else:
            file_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'htdocs', filename) # Build request file path

            # If directory traversal attacks is detected, return 403
            if not os.path.commonpath([os.path.realpath(file_path), os.path.join(os.path.dirname(os.path.abspath(__file__)), 'htdocs')]) == os.path.join(os.path.dirname(os.path.abspath(__file__)), 'htdocs'):
                standard_response(client_connection, client_address, log_queue, is_keep_alive, access_time, filename, 403)

            # If the requested file not exists, return 404
            elif not os.path.exists(file_path):
                standard_response(client_connection, client_address, log_queue, is_keep_alive, access_time, filename, 404)

            # If the requested file has not been modified, return 304
            elif browser_time and int(os.path.getmtime(file_path)) <= int(browser_time):
                standard_response(client_connection, client_address, log_queue, is_keep_alive, access_time, filename, 304)

            else:
                file_type = "application/octet-stream" if mimetypes.guess_type(file_path)[0] == None else mimetypes.guess_type(file_path)[0] # Detect the file type

                with open(file_path, 'rb') as read_file:
                    file_content = read_file.read()

                standard_response(client_connection, client_address, log_queue, is_keep_alive, access_time, filename, 200, file_type, file_content, os.path.getmtime(file_path), is_head)

    client_connection.close()

# Define socket host
SERVER_HOST = '127.0.0.1'
SERVER_PORT = 8000 #

# Create socket
server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)

try:
    server_socket.bind((SERVER_HOST, SERVER_PORT))
except:
    server_socket.bind((SERVER_HOST, 0))

server_socket.listen()

SERVER_PORT = server_socket.getsockname()[1] # Retrieve the actual port assigned

print('Listening on port ', SERVER_PORT,' ...') # Display the server startup message and the port number

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

os.makedirs(os.path.join(os.path.dirname(os.path.abspath(__file__)), 'htdocs'), exist_ok=True) # Create the file directory if it does not exist.
with open(os.path.join(os.path.dirname(os.path.abspath(__file__)), 'htdocs', 'index.html'), 'w') as write_file: # Create a default index.html file inside the htdocs directory.
    write_file.write(index_web_code)

# set stop event
log_file_stop_event = threading.Event()
request_stop_event = threading.Event()

# Create log_queue thread
log_queue = Queue()
log_thread = threading.Thread(
    target = handle_log_file,
    args = (log_queue, log_file_stop_event,)
    )
log_thread.start()

request_thread_list = [] # To store all request-handling threads.
server_socket.settimeout(1) # Prevent the thread from being blocked indefinitely and unable to be terminated

try:
    while True:
        try:
            # Wait for client connections
            client_connection, client_address = server_socket.accept()

            # Create a new thread
            request_thread_list.append(threading.Thread(
                target = handle_request,
                args = (client_connection, client_address, log_queue, request_stop_event,)
                ))

            request_thread_list[-1].start()
        except socket.timeout:
            pass
except KeyboardInterrupt:
    # Close socket
    server_socket.close()

    # Close request thread
    request_stop_event.set()

    # Wait for all request threads to finish
    for request_thread in request_thread_list:
        request_thread.join()

    # Close log thread
    log_file_stop_event.set()
    log_thread.join() # Wait for log thread to finish

    print('All thread stop') # Confirmation message