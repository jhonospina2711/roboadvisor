import requests
import time
from bs4 import BeautifulSoup


BASE_URL = "https://quotes.toscrape.com/"

def fetch_page(url):
   try:
       response = requests.get(url, timeout=10)
       if response.status_code == 200:
           return response.text

       else:
           print(f"Failed to fetch {url} - Status: {response.status_code}")
           return None

   except requests.RequestException as e:
       print(f"Request error: {e}")
       return None

def parse_quotes(html):
    soup = BeautifulSoup(html, "html.parser")
    quotes = []

    quote_blocks = soup.find_all("div", class_="quote")

    for block in quote_blocks:
        text = block.find("span", class_="text").get_text(strip=True)
        author = block.find("small", class_="author").get_text(strip=True)
        tags = [tag.get_text(strip=True) for tag in block.find_all("a", class_="tag")]

        quotes.append({
            "text": text,
            "author": author,
            "tags": tags
        })

    return quotes

def get_next_page(html):
    soup = BeautifulSoup(html, "html.parser")
    next_btn = soup.find("li", class_="next")

    if next_btn:
        next_link = next_btn.find("a")["href"]
        return BASE_URL + next_link

    return None

def crawl(start_url, max_pages=3):
    current_url = start_url
    all_quotes = []
    pages_visited = 0

    while current_url and pages_visited < max_pages:
        print(f"\nVisiting page {pages_visited + 1}: {current_url}")

        html = fetch_page(current_url)

        if not html:
            break

        quotes = parse_quotes(html)
        all_quotes.extend(quotes)

        current_url = get_next_page(html)
        pages_visited += 1

        time.sleep(1)

    return all_quotes

# For testing individual functions:
# if __name__ == "__main__":
#     html = fetch_page(BASE_URL)

#     if html:
#         quotes = parse_quotes(html)

#         for q in quotes:
#             print(q)

# To run the full crawler:
if __name__ == "__main__":
   data = crawl(BASE_URL, max_pages=3)
   print(f"\nTotal quotes collected: {len(data)}")
   print(data)