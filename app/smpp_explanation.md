# Explanation of SMPP Protocol Methods (Operations)

The SMPP (Short Message Peer-to-Peer) protocol is used to exchange short messages (SMS) between entities like ESME (your application) and SMSC (supplier message center / service provider).

Below is an explanation of the most important protocol methods or operations:

## 1. Bind Transmitter
- **Description:** Used to log in to the service provider (SMSC) for the purpose of **sending messages only**.
- **Usage:** When the primary goal of the system is to send advertising campaigns or OTP messages, and it does not need to receive messages from users.

## 2. Bind Receiver
- **Description:** Used to log in to the service provider for the purpose of **receiving messages only** (such as user messages or Delivery Receipts).
- **Usage:** When the supplier provides short codes (Short Codes) to receive customer replies, or to receive status reports of sent messages.

## 3. Bind Transceiver
- **Description:** Used to log in to the service provider to perform both **sending and receiving** operations together over the same connection (Session).
- **Usage:** This is the most common type in modern systems, as it allows you to send messages and receive delivery reports (DLR) and user responses at the same time.

## 4. Submit SM
- **Description:** The primary operation to send a short message from your system (ESME) to the service provider (SMSC).
- **Usage:** Used to send each individual message. It can contain options like requesting a delivery receipt.

## 5. Deliver SM
- **Description:** An incoming message from the service provider to your system.
- **Usage:** Primarily used to deliver user messages to you (MO - Mobile Originated), or to deliver delivery status reports (Delivery Receipts) for the messages you sent.

## 6. Enquire Link
- **Description:** A message sent periodically (Ping) to ensure that the connection between your system and the service provider is still active.
- **Usage:** To prevent session timeout and ensure network stability.

## 7. Unbind
- **Description:** To terminate the session gracefully and securely with the service provider.
- **Usage:** When the system is stopped or restarted, an Unbind request is sent to tell the supplier to safely close the current connection.

## 8. Query SM
- **Description:** To query the status of a previously sent message (useful if the delivery report did not arrive automatically).

## 9. Cancel SM
- **Description:** To try to cancel a message sent to the SMSC that has not yet been delivered to the recipient.
