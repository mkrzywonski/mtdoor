from openai import OpenAI
from rich.pretty import pprint
from loguru import logger as log

from . import BaseCommand, CommandRunError, CommandLoadError

MAX_TOKENS = 58

#MODEL = "gpt-3.5-turbo"
MODEL = "gpt-4o-mini"

class ChatGPT(BaseCommand):
    command = "llm"
    description = f"Talk to {MODEL}"
    help = f"""'llm !clear' to clear conversation context."""

    conversations: dict[list]
    token_count: int

    def load(self):
        self.conversations = {}
        self.max_tokens = MAX_TOKENS
        self.client = OpenAI()
        self.token_count = 0
        node_id=self.interface.getMyNodeInfo()['user']['id']
        shortName=self.interface.getMyNodeInfo()['user']['shortName']
        longName=self.interface.getMyNodeInfo()['user']['longName']
        hwModel=self.interface.getMyNodeInfo()['user']['hwModel']
        firmware=self.interface.metadata.firmware_version

        self.SYSTEM_PROMPT = f"You are the personality behind a meshtastic node in Buda, TX. The node operator's name is Mike, and the node hardware is a '{hwModel}' running firmware version {firmware}. The node ID is {node_id}, the short name is '{shortName}', and the long name is '{longName}'. Users can contact Mike by sending the 'msg' command to this node followed by the text of their message. The node also supports a 'ping' command that will reply with SNR and RSSI radio data and a 'heatmap' command which responds with the URL for a live heatmap showing other connected nodes in the area. This meshtastic node serves as a rooftop relay for other nodes and is not actively monitored by a human, so you are in charge of interacting with any users who may send messages. Try to be as helpful as possible for simple queries and give brief answers. In general stick to topics related to meshtastic, ham radio, computers and technology. Keep answers in plain text and under 200 characters."


    def reset(self, node: str):
        self.conversations[node] = [{"role": "system", "content": self.SYSTEM_PROMPT}]
        
    def add_message(self, node: str, message: str):
        if node not in self.conversations:
            self.reset(node)

        self.conversations[node].append({"role": "user", "content": message})

    def chat(self, input_message: str, node: str) -> None:
        input_message = input_message[len(self.command):].lstrip()
        if input_message[:6].lower() == "!clear":
            self.reset(node)
            self.send_dm("LLM conversation cleared.", node)
            return

        self.add_message(node, input_message)

        response = self.client.chat.completions.create(
            model=MODEL, messages=self.conversations[node], max_tokens=self.max_tokens
        )
        usage = response.usage
        self.token_count += usage.total_tokens
        log.info(f"OpenAI prompt_tokens: {usage.prompt_tokens}, completion_tokens: {usage.completion_tokens}, total_tokens: {usage.total_tokens}")

        answer = response.choices[0].message.content

        self.conversations[node].append({"role": "assistant", "content": answer})

        self.send_dm(answer, node)
    
    def invoke(self, msg: str, node: str) -> None:
        self.run_in_thread(self.chat, msg, node)
    
    def shutdown(self):
        log.info(f"LLM used {self.token_count} tokens.")
