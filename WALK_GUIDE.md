# How to do a walk

One walk, one elder, one phone. The phone stays in your pocket. You are there to listen.

## Before you go
- **Ask first.** "I'm making a small book of the plants you know. Can I record you while we walk? It stays on our computer." If they say no to the voice, do the walk anyway and only take photos.
- Keep the phone clock on automatic time. Photos and the recording are matched by timestamp.
- Turn on camera location if you want a map of the walk (optional).
- Check that your voice recorder keeps recording with the screen locked (start it, lock the phone for 10 seconds, play it back).

## On the walk
1. **Start the voice recorder as you step out, and don't stop it until you're home.** One long recording is fine.
2. Use the normal camera app. When they point at something or start talking about it, take **1–3 photos**: the whole plant, then a close-up of a leaf, flower or fruit.
3. Wait a few seconds before you move to the next plant. The pause between plants is how the stories get separated.
4. Aim for 8–15 plants in 30–40 minutes. Slow is good.
5. Take one photo of their hands holding a leaf (for the cover), if they're happy with that.

### Questions that bring out stories
| हिंदी | English |
|---|---|
| इसका नाम क्या है? गाँव में इसे क्या कहते थे? | What is it called? What did you call it in the village? |
| इसका क्या इस्तेमाल करते थे? | What did you use it for? |
| बचपन की कोई याद है इससे जुड़ी? | Do you have a childhood memory of it? |
| ये कब फूलता है, कब फल आते हैं? | When does it flower, when does it fruit? |
| आपको ये किसने सिखाया? | Who taught you this? |

The memory questions get the best answers. Let them wander.

## After the walk
Copy the **original files** to `walks/<date>/` on the laptop, using a USB cable or Google Drive/Photos download.
Don't send them through WhatsApp: it strips the photo timestamps and compresses the audio.

```
walks/2026-10-11/
  Recording_20261011_171503.m4a   (any audio format, any name)
  IMG_20261011_171622.jpg
  IMG_20261011_171630.jpg
  ...
```

Then run `uv run fieldguide process walks/2026-10-11`.
