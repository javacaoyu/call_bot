/** 外呼客户 API（6.2）：外呼前选择客户。 */

export interface Customer {
  id: string;
  name: string;
  phone: string;
  notes: string;
  created_at: string;
}

export async function fetchCustomers(): Promise<Customer[]> {
  const resp = await fetch("/api/customers");
  if (!resp.ok) throw new Error(`读取客户失败（${resp.status}）`);
  return (await resp.json()) as Customer[];
}

export async function createCustomer(
  body: Omit<Customer, "id" | "created_at">,
): Promise<Customer> {
  const resp = await fetch("/api/customers", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!resp.ok) throw new Error(`新建客户失败（${resp.status}）`);
  return (await resp.json()) as Customer;
}

export async function updateCustomer(
  id: string,
  body: Omit<Customer, "id" | "created_at">,
): Promise<Customer> {
  const resp = await fetch(`/api/customers/${id}`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!resp.ok) throw new Error(`更新客户失败（${resp.status}）`);
  return (await resp.json()) as Customer;
}

export async function deleteCustomer(id: string): Promise<void> {
  const resp = await fetch(`/api/customers/${id}`, { method: "DELETE" });
  if (!resp.ok) throw new Error(`删除客户失败（${resp.status}）`);
}
