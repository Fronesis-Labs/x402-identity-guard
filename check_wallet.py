from eth_account import Account
import getpass

Account.enable_unaudited_hdwallet_features()

mnemonic = getpass.getpass("Seed phrase: ")

account = Account.from_mnemonic(
    mnemonic,
    account_path="m/44'/60'/0'/0/0"
)

print("Derived address:", account.address)