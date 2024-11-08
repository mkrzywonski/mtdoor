from . import BaseCommand


class Echo(BaseCommand):
    command = "echo"
    description = "'echo' repeats your message back to you"
    help = "'echo <repeat this message>', or 'exit'"

    def invoke(self, msg: str, node: str) -> str:
        if msg.lower().split()[0] == "exit":
            self.session[node] = False
            return "Goodbye"
        self.session[node] = "Echo"
        if msg.lower().split()[0] == "echo":
            response = msg[5:]
        else:
            response = msg
        response += "\n\nEnter some more text, or 'exit' to quit"
        return response
