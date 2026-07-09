import httpx
import gzip
import io
import csv

url = "https://assets.upstox.com/market-quote/instruments/exchange/complete.csv.gz"
resp = httpx.get(url, follow_redirects=True)
decompressed = gzip.decompress(resp.content)
reader = csv.DictReader(io.StringIO(decompressed.decode('utf-8')))

row_count = 0
for row in reader:
    if row_count == 0:
        print("Header:", list(row.keys()))
        print("First row:", row)
    row_count += 1
    if row_count > 5:
        break
print("Total parsed lines:", row_count)
