import requests

# Replace with your OpenRouter API key
API_KEY = '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'
API_URL = 'https://openrouter.ai/api/v1/chat/completions'

# Define the headers for the API request
headers = {
    'Authorization': f'Bearer {API_KEY}',
    'Content-Type': 'application/json'
}

# Define the request payload (data)
data = {
    "model": "deepseek/deepseek-chat:free",
    "messages": [{"role": "user", "content": "What is the meaning of life?"}]
}

# Send the POST request to the DeepSeek API
response = requests.post(API_URL, json=data, headers=headers)

# Check if the request was successful
if response.status_code == 200:
    print("API Response:", response.json())
else:
    print("Failed to fetch data from API. Status Code:", response.status_code)