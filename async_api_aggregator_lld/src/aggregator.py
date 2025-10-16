import asyncio
import logging
import random
from typing import List, Dict, Any

# Configure professional logging to provide insight into the process.
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)

class Aggregator:
    """
    Handles a single request to fetch and aggregate data from multiple
    downstream services concurrently, with resilience and timeouts.
    """
    def __init__(self, user_id: str, fanout_services: List[str]):
        self.user_id = user_id
        self.fanout_services = fanout_services
        logging.info(f"Aggregator created for user '{self.user_id}' with services: {self.fanout_services}")

    async def fetch_data(self, service: str) -> Dict[str, Any]:
        """
        Simulates making a real API call to a downstream service.
        Includes variable latency and a chance of failure to test resilience.
        """
        # Simulate network latency between 0.1 and 1.0 seconds.
        delay = random.uniform(0.1, 1.0)
        await asyncio.sleep(delay)

        # Simulate a random failure for a service to test exception handling.
        if "orders" in service and random.random() < 0.3: # 30% chance of failure
            raise ConnectionError(f"Could not connect to {service}")

        logging.info(f"Successfully fetched data from {service} in {delay:.2f}s")
        return {"service": service, "user_id": self.user_id, "data": f"some_data_from_{service}"}

    async def aggregate(self, timeout: float = 1.5) -> Dict[str, Any]:
        """
        Orchestrates the concurrent fetching and aggregation of data.

        This method implements the core patterns for a resilient service:
        1. Creates concurrent tasks for all service calls.
        2. Wraps the entire operation in a timeout (`asyncio.wait_for`).
        3. Gathers results, treating exceptions as results (`return_exceptions=True`).
        4. Inspects the results to build a final, clean JSON-friendly response,
           providing partial data in case of individual service failures.

        Args:
            timeout: The overall deadline in seconds for the aggregation.

        Returns:
            A dictionary containing the aggregated data and/or error messages.
        """
        tasks = [asyncio.create_task(self.fetch_data(service))
                 for service in self.fanout_services]

        try:
            # 1. `asyncio.wait_for` enforces the overall SLO/deadline.
            # 2. `asyncio.gather` runs all tasks concurrently.
            # 3. `return_exceptions=True` is CRITICAL. It ensures that one
            #    failed task does not crash the entire operation.
            results = await asyncio.wait_for(
                asyncio.gather(*tasks, return_exceptions=True),
                timeout=timeout
            )

            final_response: Dict[str, Any] = {}
            has_errors = False

            # This loop is the final, crucial step. It inspects the results
            # to build a clean response, separating successful data from failures.
            for service_name, result in zip(self.fanout_services, results):
                if isinstance(result, Exception):
                    has_errors = True
                    # For an actual service, log the full exception for debugging.
                    logging.error(f"Service '{service_name}' failed: {result}")
                    # For the client, return a clean, serializable error message.
                    final_response[service_name] = {"error": f"Failed to fetch data from {service_name}."}
                else:
                    # The result was successful.
                    final_response[service_name] = result

            return {
                "status": "partial_success" if has_errors else "success",
                "data": final_response
            }

        except asyncio.TimeoutError:
            logging.error(f"Global timeout of {timeout}s exceeded.")
            # On timeout, it's best practice to cancel the lingering tasks
            # to free up resources immediately.
            for task in tasks:
                task.cancel()
            return {"status": "timeout", "error": f"Request timed out after {timeout}s."}