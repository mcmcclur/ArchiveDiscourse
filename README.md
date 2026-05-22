# ArchiveDiscourse

Archives a Discourse site into static HTML.

Forked and adapted using Codex from: https://github.com/kitsandkats/ArchiveDiscourse  
which was originally  
forked and adapted from: https://github.com/mcmcclur/ArchiveDiscourse  

This is so Meta!  
https://meta.discourse.org/t/a-basic-discourse-archival-tool/62614

## Examples

One of my simple class fora:  
https://marksmath.org/classes/Spring2026MML/discourse/

And Discourse Meta:  
https://marksmath.org/share/discourse/


## Comments

Some version or another of this repo has been frequently referred to as a useful tool for archiving general discourse sites. Be aware though that

- the recent enhancement have been largely created with Codex and
- my primary objectives have largely been centered on my own use case as a class discussion forum for university level mathematics.

There are a couple of specific features of the archiver that are of interest for mathematics:

- mathematical content is automatically typeset with MathJax V4, [as described here](https://marksmath.org/classes/Spring2026MML/discourse/t/how-do-i-enter-groovy-typeset-mathematics-into-discourse/18/) and
- fenced code blocks tagged as `sage` are translated to active Sage Cells, [as described here](https://marksmath.org/classes/Spring2026MML/discourse/t/sage-cells/172/).

## Installation and basic usage

If you fork this directory and cd into it, you can install the requirements like so:

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

Once installed, you could archive recent activity on Discourse Meta like so:

    python archive-discourse.py --base-url=https://meta.discourse.org/ --max-topics=100

I've never tried to archive all of a huge form like this and am unsure what would happen.


## Options and environment variables

In lieu of proper documentation, here's an illustration of the kinds of options that are available:

```bash
python archive-discourse.py \
  --api-key "your-api-key" \
  --api-username "your-archive-user" \
  --base-url "https://your-discourse.example" \
  --output-dir "export" \
  --archive-blurb "My groovy forum archived May, 2026." \
  --max-topics 1000 \
  --max-topic-display 30 \
  --request-delay 1 \
  --progress-every 5
```

Generally, there are reasonable defaults for these and the default values can be set with environment variables. Thus, I could put the following in a .profile:

```bash
export DISCOURSE_API_USERNAME="my_name"
export DISCOURSE_API_KEY="my_api_key"
export DISCOURSE_BASE_URL="https://discourse.mysite.org/"
```

Then, I can just run the command 

```bash
python archive-discourse.py
```

Of course, this is particularly convenient for dealing with API keys.


