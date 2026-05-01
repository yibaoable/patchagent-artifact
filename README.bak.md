# NVWA Documentation

## Quick Start Guide

This section provides the basic commands to get started with the NVWA tool for the `mruby` project, using the model GPT-4 Turbo.

```bash
# Set your OpenAI API key
export OPENAI_API_KEY=<your api key>

# Run the NVWA tool with the specified project and issue tag
./nwtool --project mruby --tag 55b5261-null_pointer_deref --model gpt-4-turbo
```

## Setting Up LiteLLM

LiteLLM enables integration with other Large Language Models (LLMs). Follow these steps to set up LiteLLM using Docker Compose.

```bash
# Start the PostgreSQL database
docker compose up -d --build postgres

# Start the LiteLLM service
docker compose up -d --build litellm
```

## Maintainers

For further information and assistance, please reach out to the project maintainer:

- [Zheng Yu](https://github.com/cla7aye15I4nd)
