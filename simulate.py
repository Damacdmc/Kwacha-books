"""Chat with the bot in your terminal - no WhatsApp account needed.

    python simulate.py

Paste a payment SMS (end with an empty line) or type commands like 'today'.
"""
from kwacha_books.bot import Bot
from kwacha_books.ledger import Ledger

PHONE = "260970000001"


def main():
    bot = Bot(Ledger("simulator.db"))
    print("Kwacha Books simulator. Type 'quit' to exit. Paste multi-line SMS and finish with an empty line.\n")
    while True:
        lines = []
        try:
            line = input("you> ")
        except EOFError:
            break
        if line.strip().lower() == "quit":
            break
        lines.append(line)
        # allow multi-line pastes
        while line and len(line) > 60:
            line = input("...  ")
            lines.append(line)
        for reply in bot.handle(PHONE, "\n".join(l for l in lines if l)):
            print("\nbot> " + reply.text.replace("\n", "\n     "))
            if reply.document:
                print(f"     [file: {reply.document}]")
            print()


if __name__ == "__main__":
    main()
