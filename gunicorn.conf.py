# gunicorn.conf.py
import multiprocessing

# Worker configuration
workers = 2
worker_class = "sync"
worker_connections = 1000
timeout = 120  # Increased timeout
keepalive = 5
max_requests = 1000
max_requests_jitter = 100

# Server socket
bind = "0.0.0.0:10000"
backlog = 2048

# Logging
accesslog = "-"
errorlog = "-"
loglevel = "info"

# Process naming
proc_name = "klumus_app"