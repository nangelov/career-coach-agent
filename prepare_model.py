import os
from transformers import pipeline
import torch

class Model:
    def __init__(self, model_id="openai-community/gpt2-large", local_dir="./models"):
        """
        Initialize the model using pipeline API, loading from local directory if available.
        
        Args:
            model_id: The Hugging Face model ID
            local_dir: Local directory to save/load the model from
        """
        self.model_id = model_id
        self.local_dir = local_dir
        self.model_path = os.path.join(local_dir, model_id.split("/")[-1])
        
        # Check if model directory exists
        if self._is_model_downloaded():
            print(f"Loading model from local directory: {self.model_path}")
            self._load_local_pipeline()
        else:
            print(f"Model not found locally. Downloading from {model_id}...")
            self._download_and_save_pipeline()
            
        # Set up chat template
        self._setup_chat_template()
    
    def _setup_chat_template(self):
        """Set up a default chat template for the tokenizer"""
        # Simpler chat template that works better with GPT-2
        chat_template = """{% for message in messages %}{% if message['role'] == 'user' %}User: {{ message['content'] }}{% elif message['role'] == 'assistant' %}Assistant: {{ message['content'] }}{% elif message['role'] == 'system' %}System: {{ message['content'] }}{% endif %}
{% endfor %}{% if add_generation_prompt %}Assistant: {% endif %}"""
        
        self.pipe.tokenizer.chat_template = chat_template
        # Set pad token to a different value than eos token
        self.pipe.tokenizer.pad_token = self.pipe.tokenizer.eos_token
        print("Chat template configured successfully")
    
    def _is_model_downloaded(self):
        """Check if model files exist in the local directory"""
        # Check for essential files
        config_path = os.path.join(self.model_path, "config.json")
        tokenizer_path = os.path.join(self.model_path, "tokenizer_config.json")
        
        if not os.path.exists(self.model_path):
            return False
        
        return os.path.exists(config_path) and os.path.exists(tokenizer_path)
    
    def _load_local_pipeline(self):
        """Load the model from the local directory using pipeline"""
        try:
            # Ensure the directory exists
            os.makedirs(self.local_dir, exist_ok=True)
            
            # Use the appropriate pipeline type
            self.pipe = pipeline(
                "text-generation",
                model=self.model_path,
                device_map="auto",
                trust_remote_code=True
            )
            
            # Test if the pipeline works
            _ = self.pipe("Hello", max_new_tokens=1)
            print("Model loaded successfully from local directory.")
        except Exception as e:
            print(f"Error loading model from local directory: {e}")
            print("Attempting to download fresh model...")
            self._download_and_save_pipeline()
    
    def _download_and_save_pipeline(self):
        """Download the model from Hugging Face and save to the local directory"""
        try:
            # Create pipeline from HF model
            self.pipe = pipeline(
                "text-generation",
                model=self.model_id,
                device_map="auto",
                trust_remote_code=True
            )
            
            # Save with safetensors format which requires less memory
            os.makedirs(self.model_path, exist_ok=True)
            self.pipe.model.save_pretrained(
                self.model_path,
                safe_serialization=True,  # Use safetensors format
                max_shard_size="4GB"  # Use smaller shards
            )
            self.pipe.tokenizer.save_pretrained(self.model_path)
            
            print(f"Model downloaded and saved to {self.model_path}")
        except Exception as e:
            raise Exception(f"Failed to download and save model: {e}")
    
    def generate(self, prompt, max_new_tokens=100):
        """Generate text based on the prompt"""
        print(f"DEBUG: Generating with prompt: {prompt[:50]}...")
        
        try:
            # Check if prompt is a list of messages or a string
            if isinstance(prompt, list):
                # Handle chat messages format
                print("DEBUG: Using chat format")
                # Format the chat messages into a single string
                formatted_chat = self.pipe.tokenizer.apply_chat_template(
                    prompt,
                    tokenize=False,
                    add_generation_prompt=True
                )
                
                # Use the pipeline directly with the formatted string
                result = self.pipe(
                    formatted_chat,
                    max_new_tokens=max_new_tokens,
                    do_sample=True,
                    temperature=0.7,
                    return_full_text=False
                )
                print(f"DEBUG: Got result: {result[0]['generated_text'][:50]}...")
                return result[0]['generated_text'].strip()
            else:
                # Handle string prompt format
                print("DEBUG: Using string format")
                result = self.pipe(
                    prompt, 
                    max_new_tokens=max_new_tokens,
                    do_sample=True,
                    temperature=0.7,
                    return_full_text=False
                )
                print(f"DEBUG: Got result: {result[0]['generated_text'][:50]}...")
                return result[0]["generated_text"]
        except Exception as e:
            print(f"DEBUG: Error during generation: {e}")
            raise e
    
    def get_tokenizer(self):
        """Return the tokenizer from the pipeline"""
        return self.pipe.tokenizer
    
    def get_model(self):
        """Return the model from the pipeline"""
        return self.pipe.model

# Example usage
if __name__ == "__main__":
    # Test with both string and chat format
    model = Model(model_id="openai-community/gpt2-large")
    
    # String format
    print("\nString format test:")
    print(model.generate("Hello, how are you?"))
    
    # Chat format
    print("\nChat format test:")
    messages = [
        {"role": "system", "content": "You are a helpful AI assistant."},
        {"role": "user", "content": "Who are you?"},
    ]
    print(model.generate(messages))
