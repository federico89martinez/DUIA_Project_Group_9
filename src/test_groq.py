from dotenv import load_dotenv
from langchain_groq import ChatGroq

load_dotenv()  # lee GROQ_API_KEY del .env

llm = ChatGroq(model="openai/gpt-oss-120b", temperature=0)
print(llm.invoke("Decime hola en una frase").content)