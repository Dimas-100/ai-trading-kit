# Step 1: Connect your broker to your AI

**What you get:** your AI assistant can see your balances, positions, orders and prices, and answer
questions about them. It cannot place, change or cancel an order.

**Do it:** `aitk connect`

## How the connection works

Your AI app does not talk to your broker directly. It starts a small program on your computer, and that
program talks to the broker's own official connector.

    your AI app  ->  the kit's guard  ->  the broker's official connector  ->  your broker

The guard does one job: it removes every tool that could change your account before your AI ever sees
it. If a tool is called by name anyway, the guard refuses and sends nothing to the broker.

## Where your keys are

In your computer's own password vault (Windows Credential Manager, macOS Keychain, or the Linux
keyring). They are not in the project folder, not in your AI app's settings file, and the kit never
prints them.

## Four kinds of connection

| The wizard says | What it means |
|---|---|
| read-only, enforced by the kit | The guard is in place. This is the strongest. |
| read-only by the broker's design | The broker's connector cannot trade at all. |
| read-only if you choose so while signing in | You tick the permissions yourself at the broker. Tick only the ones that read. |
| NOT read-only | The broker offers no way to switch trading off. The wizard asks before going on. |

## If something fails

Run `aitk check`. It re-tests every connection and says what to fix.
