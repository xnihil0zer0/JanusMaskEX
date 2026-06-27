import urllib.request
import time

papers = {
    "swe_agent.pdf": "https://arxiv.org/pdf/2405.15793.pdf",
    "intercode.pdf": "https://arxiv.org/pdf/2306.14898.pdf",
    "self_debugging.pdf": "https://arxiv.org/pdf/2304.05128.pdf"
}

headers = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/58.0.3029.110 Safari/537.3'
}

for filename, url in papers.items():
    print(f"Downloading {filename} from {url}...")
    try:
        req = urllib.request.Request(url, headers=headers)
        with urllib.request.urlopen(req) as response:
            with open(filename, 'wb') as out_file:
                out_file.write(response.read())
        print(f"Successfully downloaded {filename}")
    except Exception as e:
        print(f"Failed to download {filename}: {e}")
    time.sleep(2) # Sleep for 2 seconds to be polite to arXiv
