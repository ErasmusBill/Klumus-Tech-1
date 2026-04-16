# gunicorn.conf.py
import multiprocessing
import os

# Worker configuration
workers = max(multiprocessing.cpu_count() * 2 - 1, 2)
worker_class = "sync"
worker_connections = 1000
timeout = 120  # Increased timeout
keepalive = 5
max_requests = 1000
max_requests_jitter = 100

# Server socket
bind = f"0.0.0.0:{os.environ.get('PORT', '8000')}"
backlog = 2048

# Logging
accesslog = "-"
errorlog = "-"
loglevel = "info"

# Process naming
proc_name = "klumus_app"
