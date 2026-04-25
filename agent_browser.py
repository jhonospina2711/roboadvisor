from langchain_ollama import ChatOllama
from langchain.agents import create_agent
from langchain_community.agent_toolkits.playwright.toolkit import PlayWrightBrowserToolkit
from playwright.async_api import async_playwright
import asyncio
import os
from dotenv import load_dotenv

load_dotenv()


async def main():
    model_name = os.getenv("LOCAL_MODEL", "gemma4-financiero")

    llm = ChatOllama(
        model=model_name,
        temperature=0
    )

    pw = await async_playwright().start()
    browser = await pw.chromium.launch(headless=False)
    toolkit = PlayWrightBrowserToolkit.from_browser(async_browser=browser)
    tools = toolkit.get_tools()

    agent = create_agent(
        llm,
        tools=tools,
        system_prompt=(
            "You can use a web browser, you can click on buttons, search on inputs, and look up any information on any website."
        )
    )

    result = await agent.ainvoke({
        "messages": [
            {
                "role": "user",
                "content": """
                Go to https://quotes.toscrape.com/
                Look at the first quote and translate it to three languages:
                spanish, japanese and swahili
                """
            }
        ]
    })

    response = result["messages"][-1].content
    print(response)

if __name__ == "__main__":
    asyncio.run(main())
