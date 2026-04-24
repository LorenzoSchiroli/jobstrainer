import os
import sys
from dotenv import load_dotenv
from groq import Groq

from enricher.enricher import enrich

load_dotenv()


def main():
    if len(sys.argv) < 3:
        print("Usage: python -m enricher \"<company name>\" \"<location>\"")
        sys.exit(1)
    name = sys.argv[1]
    location = sys.argv[2]
    api_key = os.environ.get("GROQ_API_KEY")
    if not api_key:
        print("Error: GROQ_API_KEY is not set. Add it to your .env file.", file=sys.stderr)
        sys.exit(1)
    client = Groq(api_key=api_key)
    profile = enrich(name, location, client)
    for field in vars(profile):
        value = getattr(profile, field)
        print(f"{field}: {value}")


if __name__ == "__main__":
    main()
