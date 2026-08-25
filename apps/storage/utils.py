import math

def format_bytes(bytes_num: int) -> str:
    if not bytes_num or bytes_num <= 0:
        return '0 B'
    k = 1024
    sizes = ['B', 'KB', 'MB', 'GB', 'TB']
    i = int(math.floor(math.log(bytes_num, k)))
    i = min(i, len(sizes) - 1)
    val = round(bytes_num / (k ** i), 1)
    if val == int(val):
        val = int(val)
    return f"{val} {sizes[i]}"
