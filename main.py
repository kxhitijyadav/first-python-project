print("Welcome to News Finder!\n")

import requests

query = input("what type of news are you intersted in?\n")

api = "47c241498e4545108ea760d9a48fc923"


url = f"https://newsapi.org/v2/everything?q={query}&from=2026-03-06&sortBy=publishedAt&apiKey={api}"

# print(url)

r = requests.get(url) #Sends request to server
data = r.json() #API returns data in JSON format (like dictionary)

articles = data["articles"] #[articles] is now a list of news items

for index, article in enumerate(articles):
    print(index + 1, article["title"], article["url"])
    print("\n*****************************\n")