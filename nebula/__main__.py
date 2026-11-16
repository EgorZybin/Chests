import asyncio

from dotenv import load_dotenv

load_dotenv()

from nebula.bot import run


def main() -> None:
    asyncio.run(run())


if __name__ == "__main__":
    main()
