print("Welcome to News Finder!\n")

import requests

query = input("what type of news are you intersted in?\n")

api = "47c241498e4545108ea760d9a48fc923"


url = f"https://newsapi.org/v2/everything?q={query}&sortBy=publishedAt&apiKey={api}"

# print(url)

r = requests.get(url) #Sends request to server
data = r.json() #API returns data in JSON format (like dictionary)

if data.get("status") != "ok":
    print("Error from API:", data.get("message"))
else:
    articles = data["articles"]
    for index, article in enumerate(articles[:5]):
        print(f"{index + 1}. {article['title']}")
        print(f"   URL: {article['url']}")
        print("\n***************************\n")