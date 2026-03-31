import sys
from shared.chain_launcher import launch_chain

if __name__ == "__main__":

    if len(sys.argv) < 3:
        print("Usage: python trigger_chain.py <target> <product>")
        sys.exit(1)

    target = sys.argv[1]
    product = sys.argv[2]

    launch_chain(target, product)
