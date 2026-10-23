CLIPFORGE: turn long YouTube videos into captioned Shorts
==========================================================

FIRST TIME SETUP (about 10 minutes)
-----------------------------------
1. Unzip this folder somewhere easy, like your Desktop or Documents.
   (Right click the zip > Extract All. Don't run it from inside the zip.)
2. Double-click install.bat.
   - If Windows shows "Windows protected your PC", click "More info" > "Run anyway".
   - If it says Python was just installed, close the window and run install.bat again.
3. Get an Anthropic API key:
   - Go to console.anthropic.com, sign up, add a few dollars of credit.
   - Go to "API Keys" > "Create Key" and copy it (starts with sk-ant-).
   - Each hour-long video costs roughly 5 to 20 cents to analyze.

UPDATES
-------
start.bat checks GitHub for a new version every time you open it and installs it
automatically. Your settings, API key, sounds, clips and history are never touched.

TOP LIST FROM LINKS (fastest way to a Top 5)
--------------------------------------------
On the home screen click "Top List from Links". Pick Top 3/5/7/10, type the title,
paste a YouTube or TikTok link in each box (add a label if you like), choose who
ranks them, and click "Make my Top 5". ClipForge downloads each video, keeps the
best few seconds, builds the countdown (#1 last) and opens the editor. Pick music
and a style, then Render.

STYLES (make every Top List look the same)
------------------------------------------
Home > Styles. Paste a link to (or upload) a Top list Short you like and click
"Copy style": ClipForge measures its cuts, pacing and flashes (free), then Claude
looks at a few frames and copies the title, rank number and label design (a few
cents, asks first). Check the preview, tweak anything, name it, Save. Then pick it
under "Style" in Top List from Links and every video comes out in that format.
Extra fonts: put .ttf files in the fonts folder and restart ClipForge.

EVERY TIME YOU USE IT
---------------------
(Campaign gave you video files, e.g. on Google Drive? Download them, then use
"Upload a video file" next to the link box instead of pasting a link.)

1. Double-click start.bat. Your browser opens ClipForge.
   (Keep the black window open while you work. Close it to quit.)
2. First time only: click Settings, paste your API key, Save.
3. Paste a YouTube link and click "Find clips".
4. Watch each suggestion with "Preview". Tick "Use this clip" on the ones you like.
   - Trim with the -0.5s / +0.5s buttons, or pause the player and press "Start = now" / "End = now".
   - "Edit captions" lets you fix wrong words.
   - "+ Sound effect" adds a whoosh, pop, ding, etc. at a moment you choose.
5. Pick your caption style, framing and music on the left.
6. Click "Render". Finished MP4s appear with a Download button,
   and are also saved in the "output" folder.

MONEY AND SPENDING
------------------
- Only "Find clips" costs money. Everything else is free.
- Before every charge, ClipForge shows the expected cost and waits for you to
  click "Yes, spend it". Cancel is always free.
- The "AI spend" button at the top shows what ClipForge has spent and a history.
  Set your budget there to the credit you bought.
- ClipForge can't see your real balance. The official numbers are at
  console.anthropic.com under Billing / Usage.

YOUR OWN SOUNDS AND MUSIC
-------------------------
Use the "Add my music" / "Add my sound effects" buttons, or drop MP3/WAV files into:
  sounds\my_music
  sounds\my_sfx
The bundled starter sounds were generated from scratch for this app and are free to use.
Good free libraries: YouTube Audio Library (in YouTube Studio) and pixabay.com/sound-effects.
Don't use popular songs: Content ID will flag them.

MONTAGE (join several short clips)
----------------------------------
Click "Make a montage", add your clips (upload files, or paste YouTube links one
at a time with "Add from link"; for videos over 20 minutes type From/To so only
that part downloads), trim each one ("from"/"to" in seconds),
put them in order with Up/Down, then "Build montage".
Shortcut: pick a target length and click "Auto-pick best parts (free)". It keeps the
loudest, most action-packed part of each clip and puts the strongest one first. You get one clip, already
ticked, with a whoosh at every cut. Add a voiceover and click Render.
Keep the total at 60 seconds or less for YouTube Shorts.

TOP LIST (Top 3 / 5 / 7 / 10 countdowns): in Montage, set Format to "Top list
countdown", pick how many, type the title, add your clips, click "Auto-pick best
parts" (it ranks them, #1 at the top), add a label per clip, then Build. The video
counts down and shows #1 last, with the rank number and title on screen.

GAMEPLAY CLIPS (Roblox, Fortnite, etc.)
---------------------------------------
Under "What kind of video?" pick "Gameplay: find hype moments". ClipForge listens
for the loudest, most exciting moments (free, no AI). Loud doesn't always mean
good, so preview each one before you use it.

AI VOICEOVER
------------
On any clip, click "+ AI voiceover". Type what the voice should say (free), or
click "Write it with AI": Claude looks at a few frames of the clip and writes a
short script (about 1 to 3 cents, and it asks first). Press "Hear it" to check
it fits. The game audio gets quieter while the voice talks. Captions can show
the voice's words. Voices are free Microsoft voices through an unofficial tool,
so if they stop working one day, open start.bat again (it updates the tool).
Check each campaign's rules: some don't allow AI voices.

SOUND LAB (make your own sounds)
-------------------------------
Click "Sound Lab" at the top. Paste a YouTube link or upload a video/audio file.
- Cut one sound: drag across the waveform (or type Start/End), then "+ Add to list".
- Split a compilation: click "Find sounds" to cut it wherever there's silence.
- Untick what you don't want, name the rest, then "Save checked sounds".
Sound Lab is free (no AI). Sounds taken from other people's videos can still get
Content ID claims, so prefer channels that say their sounds are free to use.

FRAMING OPTIONS
---------------
- Follow the face: finds the biggest face and moves the crop when it changes.
  Works best with one person on screen. With two people side by side it picks
  one of them, not necessarily the one talking.
- Whole frame + blurred background: shows the full video in the middle. Best for
  two-person podcast shots.
- Left / Center / Right: a fixed crop.

TIMING
------
- Finding clips: 1 to 3 minutes (uses YouTube's captions).
- If a video has no captions, ClipForge transcribes it on your computer with Whisper.
  That's slow without an NVIDIA card: roughly 20 to 40 minutes per hour of video,
  and the first time it downloads a ~500 MB model.
- Rendering: about 1 to 3 minutes per clip.

IF SOMETHING BREAKS
-------------------
- "Sign in to confirm you're not a bot" or download errors: YouTube changes often.
  Close ClipForge and open start.bat again (it updates the downloader each time).
- "FFmpeg was not found": run install.bat again, then restart your computer.
- Analyzing the same video twice reuses the saved result for free. Tick
  "Ask Claude again" if you want fresh suggestions.

A NOTE ON COPYRIGHT
-------------------
Posting clips of other creators without permission can get Content ID claims,
copyright strikes (3 strikes deletes a channel), and keeps you out of the YouTube
Partner Program under the "reused content" policy. Many podcasters and streamers
run official clipping programs or will give permission if you ask. Downloading
from YouTube is also against YouTube's Terms of Service.
