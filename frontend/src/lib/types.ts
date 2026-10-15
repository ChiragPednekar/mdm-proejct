export type Role = "admin" | "service_manager" | "technician";
export interface User { user_id: number; username: string; email: string; full_name: string; role: Role; technician_id: number | null }
export interface Page<T> { items: T[]; total: number; page: number; page_size: number }

export interface Customer {
  customer_id: number; full_name: string; email: string | null; phone: string | null; address: string | null;
  city: string | null; created_at: string; product_count?: number; service_request_count?: number;
}
export interface ProductModel {
  product_model_id: number; manufacturer: string; model_name: string; product_category: string;
  model_description: string | null; standard_warranty_months: number; release_year: number;
}
export interface FaultCategory {
  fault_category_id: number; name: string; description: string | null; is_customer_induced: boolean;
  is_wear_and_tear: boolean; counts_as_failure: boolean;
}
export interface Component { component_id: number; component_name: string; component_category: string; manufacturer: string | null }
export interface Technician { technician_id: number; full_name: string; email: string; specialization: string; employment_status: string }
export interface ProductRow {
  product_id: number; serial_number: string; purchase_date: string; purchase_price: number; product_status: string;
  product_model_id: number; manufacturer: string; model_name: string; product_category: string; customer_id: number;
  customer_name: string; coverage_status: string; risk_level: string | null; failure_probability: number | null;
}
export interface Warranty {
  warranty_id: number; product_id: number; parent_warranty_id: number | null; warranty_type: string; start_date: string;
  end_date: string; coverage_details: string | null; covers_parts: boolean; covers_labor: boolean;
  covers_wear_and_tear: boolean; covers_accidental_damage: boolean; warranty_status: string; extended_warranty: boolean;
  effective_status: string; days_remaining: number; serial_number?: string; model_name?: string; customer_name?: string;
  product_category?: string;
}
export interface Prediction {
  prediction_id: number; prediction_date: string; prediction_horizon_days: number; failure_probability: number;
  risk_level: "Low" | "Medium" | "High"; model_version: string; model_classification: "validated" | "demonstration";
  explanation: string; explanation_details: { feature: string; label: string; value: unknown; typical_value: unknown; contribution: number }[] | null;
  feature_snapshot?: Record<string, unknown>; prediction_status: string;
  product_id?: number; serial_number?: string; model_name?: string; product_category?: string;
  decision_threshold?: number | null; above_decision_threshold?: boolean;
}
export interface RepairPartLine { part_id: number; part_number: string; part_name: string; quantity_used: number; unit_cost_at_repair: number; line_total: number }
export interface Repair {
  repair_id: number; attempt_number: number; technician_name: string; component_name: string | null; diagnosis: string;
  root_cause: string | null; repair_action: string; labor_cost: number; parts_cost: number; total_cost: number;
  repair_date: string; outcome: string; repeat_failure: boolean; parts: RepairPartLine[];
}
export interface ServiceRequestRow {
  service_request_id: number; product_id: number; serial_number: string; model_name: string; product_category: string;
  customer_name: string; fault_category: string; complaint_description: string; priority: string; failure_severity: string;
  request_status: string; reported_at: string; resolution_date: string | null; warranty_covered: boolean | null;
  technician_name: string | null; assigned_technician_id: number | null;
}
export interface ServiceRequestDetail {
  service_request_id: number; request_status: string; complaint_description: string; priority: string;
  failure_severity: string; reported_at: string; resolution_date: string | null; resolution_summary: string | null;
  fault_category: FaultCategory; technician: { technician_id: number; full_name: string; specialization: string } | null;
  product: { product_id: number; serial_number: string; model_name: string; manufacturer: string; product_category: string;
    product_status: string; customer_name: string; customer_phone: string | null };
  warranty: { warranty_id: number; warranty_type: string; start_date: string; end_date: string; covers_parts: boolean;
    covers_labor: boolean; effective_status: string } | null;
  warranty_covered: boolean | null; coverage_notes: string | null; repairs: Repair[];
  costs: { labor: number; parts: number; total: number; warranty: number; customer: number };
  allowed_transitions: string[]; can_record_repair: boolean; can_complete: boolean;
}
export interface Part {
  part_id: number; component_id: number | null; part_number: string; part_name: string; unit_cost: number | string;
  selling_price: number | string | null; stock_quantity: number; reorder_level: number; supplier_name: string | null;
  updated_at: string; component_name: string | null; low_stock: boolean;
}
export interface Metric { key: string; label: string; value: number | null; definition: string; [k: string]: unknown }
