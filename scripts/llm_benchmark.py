#!/usr/bin/env python3
"""LLM API Benchmark Tool - Measures latency and throughput of LLM APIs."""

import argparse
import asyncio
import time
from typing import Dict
import httpx
from statistics import mean


class LLMBenchmark:
    """Benchmark tool for testing LLM API performance."""
    
    def __init__(self, base_url: str, api_key: str, model_name: str,
                 timeout: float = 30.0, connect_timeout: float = 10.0):
        """Initialize benchmark with API details and timeout settings."""
        self.base_url = base_url.rstrip('/')
        self.model_name = model_name
        self.client = httpx.Client(
            headers=self._get_headers(api_key),
            timeout=httpx.Timeout(timeout=timeout, connect=connect_timeout)
        )
        self.async_client = httpx.AsyncClient(
            headers=self._get_headers(api_key),
            timeout=httpx.Timeout(timeout=timeout, connect=connect_timeout)
        )

    def _get_headers(self, api_key: str) -> Dict[str, str]:
        """Get standard request headers."""
        return {
            'Authorization': f'Bearer {api_key}',
            'Content-Type': 'application/json'
        }

    def _get_request_payload(self, prompt: str) -> Dict:
        """Get standardized request payload."""
        return {
            "messages": [{"role": "user", "content": prompt}],
            "model": self.model_name,
            "temperature": 0.7,
            "top_p": 1,
            "stream": False,
            "max_tokens": 100
        }

    def test_latency(self, num_requests: int = 10) -> Dict[str, float]:
        """Test latency by making sequential requests."""
        latencies = []
        endpoint = f"{self.base_url}/v1/chat/completions"
        
        for _ in range(num_requests):
            start = time.perf_counter()
            response = self.client.post(
                endpoint,
                json=self._get_request_payload("Ping")
            )
            response.raise_for_status()
            latencies.append(time.perf_counter() - start)
        
        return {
            'avg': mean(latencies),
            'min': min(latencies),
            'max': max(latencies),
            'unit': 'seconds'
        }

    async def test_throughput(self, num_requests: int = 100, 
                            concurrency: int = 10) -> Dict[str, float]:
        """Test throughput by making concurrent requests."""
        semaphore = asyncio.Semaphore(concurrency)
        start_time = time.perf_counter()
        completed = 0
        endpoint = f"{self.base_url}/v1/chat/completions"

        async def make_request():
            nonlocal completed
            async with semaphore:
                try:
                    await self.async_client.post(
                        endpoint,
                        json=self._get_request_payload("Throughput test")
                    )
                    completed += 1
                except Exception as e:
                    print(f"Request failed: {e}")

        tasks = [make_request() for _ in range(num_requests)]
        await asyncio.gather(*tasks)
        
        return {
            'requests_per_second': completed / (time.perf_counter() - start_time),
            'total_requests': num_requests,
            'successful_requests': completed,
            'time_elapsed': time.perf_counter() - start_time
        }

def main():
    parser = argparse.ArgumentParser(description='LLM API Benchmark Tool')
    parser.add_argument('--base-url', required=True, help='Base URL of the LLM API')
    parser.add_argument('--api-key', required=True, help='API key for authentication')
    parser.add_argument('--model', required=True, help='Model name to test')
    parser.add_argument('--latency-requests', type=int, default=10, 
                       help='Number of requests for latency test')
    parser.add_argument('--throughput-requests', type=int, default=100,
                       help='Total requests for throughput test')
    parser.add_argument('--concurrency', type=int, default=10,
                       help='Concurrent requests for throughput test')
    parser.add_argument('--timeout', type=float, default=30.0,
                       help='Request timeout in seconds (default: 30)')
    parser.add_argument('--connect-timeout', type=float, default=10.0,
                       help='Connection timeout in seconds (default: 10)')
    
    args = parser.parse_args()

    benchmark = LLMBenchmark(
        args.base_url, 
        args.api_key, 
        args.model,
        timeout=args.timeout,
        connect_timeout=args.connect_timeout
    )
    
    print("\n=== Running Latency Test ===")
    latency_results = benchmark.test_latency(args.latency_requests)
    print(f"Average latency: {latency_results['avg']:.4f}s")
    print(f"Min latency: {latency_results['min']:.4f}s")
    print(f"Max latency: {latency_results['max']:.4f}s")

    print("\n=== Running Throughput Test ===")
    throughput_results = asyncio.run(
        benchmark.test_throughput(args.throughput_requests, args.concurrency)
    )
    print(f"Requests per second: {throughput_results['requests_per_second']:.2f}")
    print(f"Successful requests: {throughput_results['successful_requests']}/{args.throughput_requests}")
    print(f"Time elapsed: {throughput_results['time_elapsed']:.2f}s")

if __name__ == '__main__':
    main()
