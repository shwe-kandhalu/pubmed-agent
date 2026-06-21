# PubMed Research Agent

An AI-powered research assistant that searches PubMed, retrieves full-text papers from PubMed Central, and synthesizes scientific literature using Claude.

## How it works

1. You ask a research question
2. The agent searches PubMed — and refines its query if initial results are sparse
3. It screens abstracts to identify the most relevant papers
4. For the top papers, it fetches full text (methods, results, discussion) from PubMed Central
5. Claude synthesizes a structured report with key findings, themes, clinical implications, and research gaps

## Setup

1. Clone the repo:
   ```
   git clone https://github.com/shwe-kandhalu/pubmed-agent.git
   cd pubmed-agent
   ```

2. Install dependencies:
   ```
   pip3 install -r requirements.txt
   ```

3. Add your Anthropic API key:
   ```
   cp .env.example .env
   ```
   Then open `.env` and replace `your-key-here` with your actual key from [console.anthropic.com](https://console.anthropic.com).

## Usage

```
python3 agent.py "your research question here"
```

Or run without arguments to be prompted interactively:

```
python3 agent.py
```

## Example

```
python3 agent.py "GWAS of age at menarche"
```

**Output:**
```
Key Findings
- Epigenetic regulation: 63 differentially methylated regions associated with age at menarche...
- Mental health links: Significant shared genetic architecture with depression, self-harm...
- Bone health: Later menarche causally associated with higher osteoporosis risk (OR: 1.59)...

Common Themes
- Pleiotropic genetic architecture across cardiometabolic and neuropsychiatric traits
- Mendelian randomization as primary causal inference tool
...
```

## Stack

- [Claude](https://anthropic.com) — LLM reasoning and report generation
- [NCBI E-utilities](https://www.ncbi.nlm.nih.gov/books/NBK25497/) — PubMed search, abstract retrieval, and PubMed Central full-text access
- Python `requests` for API calls
