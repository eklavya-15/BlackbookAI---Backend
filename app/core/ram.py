import psutil
import os

def ram():
    process = psutil.Process(os.getpid())
    return process.memory_info().rss / 1024 / 1024