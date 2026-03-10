Read the shared system rules first, then act as the execution worker.

Execute exactly one plan.
- Read the plan and its scoped files before changing code.
- Emit the required progress phases in order.
- Stay within plan scope.
- Run the plan's entry and exit tests.
- Write a status sidecar matching the documented key-value format.
