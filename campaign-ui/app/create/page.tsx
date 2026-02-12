"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import CampaignForm from "@/components/CampaignForm";
import CampaignChat from "@/components/CampaignChat";
import { CampaignFormData } from "@/lib/types";

export default function CreateCampaignPage() {
	const router = useRouter();
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

	const handleCampaignCreated = (campaignId: string) => {
		setTimeout(() => {
			router.push(`/campaigns/${campaignId}`);
		}, 500);
	};

	const handleFormUpdate = (updates: Partial<CampaignFormData>) => {
		setFormData((prev) => ({ ...prev, ...updates }));
	};

	return (
		<div className="space-y-6">
			<div>
				<h1 className="text-2xl font-bold text-primary">
					Create New Campaign
				</h1>
				<p className="text-gray-70 mt-1">
					Set requirements, markets, and number of providers per
					market
				</p>
			</div>

			<div className="grid grid-cols-1 lg:grid-cols-3 gap-8">
				{/* Left: Create Campaign Form */}
				<div className="lg:col-span-2">
					<CampaignForm
						onCampaignCreated={handleCampaignCreated}
						externalUpdates={formData}
					/>
				</div>

				{/* Right: Chat Assistant */}
				<div>
					<CampaignChat
						currentFormData={formData}
						onFieldsExtracted={handleFormUpdate}
					/>
				</div>
			</div>
		</div>
	);
}
