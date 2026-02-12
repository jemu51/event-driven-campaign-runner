"use client";

import { useState, useEffect } from "react";
import { createCampaign } from "@/lib/api";
import {
	CreateCampaignInput,
	CampaignFormData as CampaignFormDataType,
} from "@/lib/types";

interface CampaignFormProps {
	onCampaignCreated: (campaignId: string) => void;
	externalUpdates?: Partial<CampaignFormDataType>;
}

interface CampaignFormData {
	campaignType: string;
	markets: string;
	providersPerMarket: number;
	requiredEquipment: string;
	requiredDocuments: string;
	insuranceMinCoverage: number;
	travelRequired: boolean;
	buyer_id?: string;
}

export default function CampaignForm({
	onCampaignCreated,
	externalUpdates,
}: CampaignFormProps) {
	const [loading, setLoading] = useState(false);
	const [error, setError] = useState<string | null>(null);

	const [formData, setFormData] = useState<CampaignFormData>({
		campaignType: "New Campaign",
		markets: "",
		providersPerMarket: 0,
		requiredEquipment: "",
		requiredDocuments: "",
		insuranceMinCoverage: 0,
		travelRequired: false,
		buyer_id: "",
	});

	// Apply external updates (from chat)
	useEffect(() => {
		if (externalUpdates) {
			setFormData((prev) => ({
				...prev,
				...externalUpdates,
				// Handle array fields that come as arrays but need to be strings
				markets: externalUpdates.markets
					? Array.isArray(externalUpdates.markets)
						? externalUpdates.markets.join(", ")
						: externalUpdates.markets
					: prev.markets,
				requiredEquipment: externalUpdates.requiredEquipment
					? Array.isArray(externalUpdates.requiredEquipment)
						? externalUpdates.requiredEquipment.join(", ")
						: externalUpdates.requiredEquipment
					: prev.requiredEquipment,
				requiredDocuments: externalUpdates.requiredDocuments
					? Array.isArray(externalUpdates.requiredDocuments)
						? externalUpdates.requiredDocuments.join(", ")
						: externalUpdates.requiredDocuments
					: prev.requiredDocuments,
			}));
		}
	}, [externalUpdates]);

	const handleSubmit = async (e: React.FormEvent) => {
		e.preventDefault();
		setLoading(true);
		setError(null);

		try {
			const input: CreateCampaignInput = {
				buyer_id: formData.buyer_id || "buyer-001",
				requirements: {
					type: formData.campaignType,
					markets: formData.markets
						.split(",")
						.map((m) => m.trim())
						.filter(Boolean),
					providers_per_market: formData.providersPerMarket,
					equipment: {
						required: formData.requiredEquipment
							.split(",")
							.map((e) => e.trim())
							.filter(Boolean),
					},
					documents: {
						required: formData.requiredDocuments
							.split(",")
							.map((d) => d.trim())
							.filter(Boolean),
						insurance_min_coverage: formData.insuranceMinCoverage,
					},
					travel_required: formData.travelRequired,
				},
			};

			const result = await createCampaign(input);
			onCampaignCreated(result.campaign_id);
		} catch (err) {
			setError(
				err instanceof Error
					? err.message
					: "Failed to create campaign",
			);
		} finally {
			setLoading(false);
		}
	};

	return (
		<form
			onSubmit={handleSubmit}
			className="bg-white rounded-xl shadow-sm border border-gray-30 p-6 space-y-5"
		>
			<h2 className="text-lg font-semibold text-primary">
				Create New Campaign
			</h2>

			<p className="text-gray-70 mt-1">
				Set requirements, markets, and number of providers per market
			</p>
			{error && (
				<div className="bg-red-20 border border-red-40 text-red-80 px-4 py-3 rounded-lg text-sm">
					{error}
				</div>
			)}

			<div className="grid grid-cols-1 md:grid-cols-2 gap-4">
				<div>
					<label className="block text-sm font-medium text-gray-80 mb-1">
						Buyer ID
					</label>
					<input
						type="text"
						value={formData.buyer_id ?? ""}
						onChange={(e) =>
							setFormData({
								...formData,
								buyer_id: e.target.value,
							})
						}
						className="w-full px-3 py-2 border border-gray-40 rounded-lg text-sm focus:ring-2 focus:ring-indigo-60 focus:border-indigo-60"
						placeholder="e.g. buyer-001"
					/>
				</div>
				<div>
					<label className="block text-sm font-medium text-gray-80 mb-1">
						Campaign Type
					</label>
					<input
						type="text"
						value={formData.campaignType}
						onChange={(e) =>
							setFormData({
								...formData,
								campaignType: e.target.value,
							})
						}
						className="w-full px-3 py-2 border border-gray-40 rounded-lg text-sm focus:ring-2 focus:ring-indigo-60 focus:border-indigo-60"
						placeholder="New Campaign"
					/>
				</div>
				<div>
					<label className="block text-sm font-medium text-gray-80 mb-1">
						Markets (comma-separated)
					</label>
					<input
						type="text"
						value={formData.markets}
						onChange={(e) =>
							setFormData({
								...formData,
								markets: e.target.value,
							})
						}
						className="w-full px-3 py-2 border border-gray-40 rounded-lg text-sm focus:ring-2 focus:ring-indigo-60 focus:border-indigo-60"
						placeholder="e.g. atlanta, chicago"
					/>
				</div>
				<div>
					<label className="block text-sm font-medium text-gray-80 mb-1">
						Providers per Market
					</label>
					<input
						type="number"
						min={1}
						max={20}
						value={formData.providersPerMarket}
						onChange={(e) =>
							setFormData({
								...formData,
								providersPerMarket:
									parseInt(e.target.value) || 1,
							})
						}
						className="w-full px-3 py-2 border border-gray-40 rounded-lg text-sm focus:ring-2 focus:ring-indigo-60 focus:border-indigo-60"
					/>
				</div>
				<div>
					<label className="block text-sm font-medium text-gray-80 mb-1">
						Required Equipment
					</label>
					<input
						type="text"
						value={formData.requiredEquipment}
						onChange={(e) =>
							setFormData({
								...formData,
								requiredEquipment: e.target.value,
							})
						}
						className="w-full px-3 py-2 border border-gray-40 rounded-lg text-sm focus:ring-2 focus:ring-indigo-60 focus:border-indigo-60"
						placeholder="e.g. bucket_truck, spectrum_analyzer"
					/>
				</div>
				<div>
					<label className="block text-sm font-medium text-gray-80 mb-1">
						Required Documents
					</label>
					<input
						type="text"
						value={formData.requiredDocuments}
						onChange={(e) =>
							setFormData({
								...formData,
								requiredDocuments: e.target.value,
							})
						}
						className="w-full px-3 py-2 border border-gray-40 rounded-lg text-sm focus:ring-2 focus:ring-indigo-60 focus:border-indigo-60"
						placeholder="e.g. insurance_certificate"
					/>
				</div>
				<div>
					<label className="block text-sm font-medium text-gray-80 mb-1">
						Min Insurance Coverage ($)
					</label>
					<input
						type="number"
						value={formData.insuranceMinCoverage}
						onChange={(e) =>
							setFormData({
								...formData,
								insuranceMinCoverage:
									parseInt(e.target.value) || 0,
							})
						}
						className="w-full px-3 py-2 border border-gray-40 rounded-lg text-sm focus:ring-2 focus:ring-indigo-60 focus:border-indigo-60"
					/>
				</div>
			</div>

			<div className="flex items-center gap-2">
				<input
					type="checkbox"
					id="travelRequired"
					checked={formData.travelRequired}
					onChange={(e) =>
						setFormData({
							...formData,
							travelRequired: e.target.checked,
						})
					}
					className="h-4 w-4 text-indigo-60 rounded border-gray-40"
				/>
				<label
					htmlFor="travelRequired"
					className="text-sm text-gray-80"
				>
					Travel Required
				</label>
			</div>

			<button
				type="submit"
				disabled={loading}
				className="w-full bg-indigo-60 hover:bg-indigo-80 disabled:bg-indigo-40 text-white font-medium py-2.5 px-4 rounded-lg transition-colors text-sm"
			>
				{loading ? "Creating Campaign..." : "Create Campaign"}
			</button>
		</form>
	);
}
