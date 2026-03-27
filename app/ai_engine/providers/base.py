from abc import ABC, abstractmethod

class BaseProvider(ABC):

    @abstractmethod
    def run(self, model: str, messages: list, timeout: int):
        """
        Must return:
        {
            "output": str,
            "tokens_input": int,
            "tokens_output": int
        }
        """
        pass
