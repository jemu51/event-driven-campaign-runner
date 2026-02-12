"use client";

import { useState } from "react";
import { useParams, useRouter } from "next/navigation";
import { useCampaign } from "@/hooks/useCampaign";
import ProviderInbox from "@/components/ProviderInbox";
import EventStream from "@/components/EventStream";
import {
	STATUS_COLORS,
	STATUS_LABELS,
	CAMPAIGN_STATUS_COLORS,
	PROVIDER_STATUS_ORDER,
} from "@/lib/types";
import { updateCampaignStatus, deleteCampaign } from "@/lib/api";

export default function CampaignPage() {
	const params = useParams();
	const router = useRouter();
	const campaignId = params.id as string;
	const { campaign, loading, error, refresh } = useCampaign(campaignId);
	const [isUpdating, setIsUpdating] = useState(false);
	const [showDeleteConfirm, setShowDeleteConfirm] = useState(false);

	if (loading && !campaign) {
		return (
			<div className="flex items-center justify-center py-20">
				<div className="animate-spin rounded-full h-8 w-8 border-b-2 border-indigo-60" />
			</div>
		);
	}

	if (error) {
		return (
			<div className="bg-red-20 border border-red-40 text-red-80 px-6 py-4 rounded-lg">
				<h3 className="font-medium">Error loading campaign</h3>
				<p className="text-sm mt-1">{error}</p>
				<button onClick={refresh} className="text-sm underline mt-2">
					Retry
				</button>
			</div>
		);
	}

	if (!campaign) return null;

	const campaignStatusColor =
		CAMPAIGN_STATUS_COLORS[campaign.status] || "bg-gray-20 text-gray-80";
	const isRunning = campaign.status === "RUNNING";
	const isStopped = campaign.status === "STOPPED";
	const isCompleted = campaign.status === "COMPLETED";

	const handlePauseResume = async () => {
		if (isUpdating) return;
		setIsUpdating(true);
		try {
			const newStatus = isRunning ? "STOPPED" : "RUNNING";
			await updateCampaignStatus(
				campaignId,
				newStatus as "STOPPED" | "RUNNING",
			);
			await refresh();
		} catch (err) {
			const message =
				err instanceof Error
					? err.message
					: "Failed to update campaign status.";
			await refresh(); // Refetch so if campaign was deleted we show error state
			if (
				message.includes("not found") ||
				message.includes("Campaign not found")
			) {
				alert(
					"Campaign no longer exists (e.g. deleted or server restarted). Returning to list.",
				);
				router.push("/");
				return;
			}
			alert(
				message ||
					"Failed to update campaign status. Please try again.",
			);
		} finally {
			setIsUpdating(false);
		}
	};

	const handleMarkCompleted = async () => {
		if (isUpdating) return;
		setIsUpdating(true);
		try {
			await updateCampaignStatus(campaignId, "COMPLETED");
			await refresh();
		} catch (err) {
			const message =
				err instanceof Error
					? err.message
					: "Failed to mark campaign as completed.";
			await refresh(); // Refetch so if campaign was deleted we show error state
			if (
				message.includes("not found") ||
				message.includes("Campaign not found")
			) {
				alert(
					"Campaign no longer exists (e.g. deleted or server restarted). Returning to list.",
				);
				router.push("/");
				return;
			}
			alert(
				message ||
					"Failed to mark campaign as completed. Please try again.",
			);
		} finally {
			setIsUpdating(false);
		}
	};

	const handleDelete = async (deleteProviders: boolean) => {
		if (isUpdating) return;
		setIsUpdating(true);
		try {
			await deleteCampaign(campaignId, deleteProviders);
			router.push("/");
		} catch (err) {
			console.error("Failed to delete campaign:", err);
			alert("Failed to delete campaign. Please try again.");
			setIsUpdating(false);
		}
	};

	return (
		<div className="space-y-6">
			{/* Header */}
			<div className="flex items-center justify-between">
				<div>
					<div className="flex items-center gap-2">
						<a
							href="/"
							className="text-gray-60 hover:text-gray-80 text-sm"
						>
							&larr; Back
						</a>
					</div>
					<div className="flex items-center gap-3 mt-1">
						<h1 className="text-2xl font-bold text-primary">
							{campaignId}
						</h1>
						<span
							className={`inline-flex items-center px-2.5 py-0.5 rounded-full text-xs font-medium ${campaignStatusColor}`}
						>
							{campaign.status}
						</span>
					</div>
					<p className="text-gray-70 text-sm">
						{campaign.total_providers} providers across{" "}
						{new Set(campaign.providers.map((p) => p.market)).size}{" "}
						markets
						{campaign.campaign_type &&
							` \u00b7 ${campaign.campaign_type}`}
					</p>
					{campaign.created_at && (
						<p className="text-xs text-gray-60 mt-0.5">
							Created{" "}
							{new Date(campaign.created_at).toLocaleString()}
						</p>
					)}
				</div>
				<div className="flex items-center gap-2">
					{!isCompleted && (
						<button
							onClick={handlePauseResume}
							disabled={isUpdating}
							className={`font-medium py-2 px-4 rounded-lg transition-colors text-sm flex items-center gap-2 ${
								isRunning
									? "bg-orange-60 hover:bg-orange-80 text-white"
									: "bg-green-60 hover:bg-green-80 text-white"
							} disabled:opacity-50 disabled:cursor-not-allowed`}
						>
							{isUpdating ? (
								<>
									<div className="w-4 h-4 animate-spin rounded-full border-2 border-white/30 border-t-white" />
									{isRunning ? "Stopping..." : "Resuming..."}
								</>
							) : (
								<>
									{isRunning ? (
										<>
											<svg
												className="w-4 h-4"
												fill="none"
												stroke="currentColor"
												viewBox="0 0 24 24"
											>
												<path
													strokeLinecap="round"
													strokeLinejoin="round"
													strokeWidth={2}
													d="M10 9v6m4-6v6m7-3a9 9 0 11-18 0 9 9 0 0118 0z"
												/>
											</svg>
											Pause Campaign
										</>
									) : (
										<>
											<svg
												className="w-4 h-4"
												fill="none"
												stroke="currentColor"
												viewBox="0 0 24 24"
											>
												<path
													strokeLinecap="round"
													strokeLinejoin="round"
													strokeWidth={2}
													d="M14.752 11.168l-3.197-2.132A1 1 0 0010 9.87v4.263a1 1 0 001.555.832l3.197-2.132a1 1 0 000-1.664z"
												/>
												<path
													strokeLinecap="round"
													strokeLinejoin="round"
													strokeWidth={2}
													d="M21 12a9 9 0 11-18 0 9 9 0 0118 0z"
												/>
											</svg>
											Resume Campaign
										</>
									)}
								</>
							)}
						</button>
					)}
					{!isCompleted && (
						<button
							onClick={handleMarkCompleted}
							disabled={isUpdating}
							className="bg-green-60 hover:bg-green-80 text-white font-medium py-2 px-4 rounded-lg transition-colors text-sm flex items-center gap-2 disabled:opacity-50 disabled:cursor-not-allowed"
						>
							{isUpdating ? (
								<>
									<div className="w-4 h-4 animate-spin rounded-full border-2 border-white/30 border-t-white" />
									Completing...
								</>
							) : (
								<>
									<svg
										className="w-4 h-4"
										fill="none"
										stroke="currentColor"
										viewBox="0 0 24 24"
									>
										<path
											strokeLinecap="round"
											strokeLinejoin="round"
											strokeWidth={2}
											d="M9 12l2 2 4-4m6 2a9 9 0 11-18 0 9 9 0 0118 0z"
										/>
									</svg>
									Mark as Completed
								</>
							)}
						</button>
					)}
					<button
						onClick={() => setShowDeleteConfirm(true)}
						disabled={isUpdating}
						className="bg-red-60 hover:bg-red-80 text-white font-medium py-2 px-4 rounded-lg transition-colors text-sm flex items-center gap-2 disabled:opacity-50 disabled:cursor-not-allowed"
					>
						<svg
							className="w-4 h-4"
							fill="none"
							stroke="currentColor"
							viewBox="0 0 24 24"
						>
							<path
								strokeLinecap="round"
								strokeLinejoin="round"
								strokeWidth={2}
								d="M19 7l-.867 12.142A2 2 0 0116.138 21H7.862a2 2 0 01-1.995-1.858L5 7m5 4v6m4-6v6m1-10V4a1 1 0 00-1-1h-4a1 1 0 00-1 1v3M4 7h16"
							/>
						</svg>
						Delete
					</button>
					<button
						onClick={refresh}
						className="bg-white border border-gray-40 hover:bg-gray-20 text-gray-80 font-medium py-2 px-4 rounded-lg transition-colors text-sm flex items-center gap-2"
					>
						<svg
							className="w-4 h-4"
							fill="none"
							stroke="currentColor"
							viewBox="0 0 24 24"
						>
							<path
								strokeLinecap="round"
								strokeLinejoin="round"
								strokeWidth={2}
								d="M4 4v5h.582m15.356 2A8.001 8.001 0 004.582 9m0 0H9m11 11v-5h-.581m0 0a8.003 8.003 0 01-15.357-2m15.357 2H15"
							/>
						</svg>
						Refresh
					</button>
				</div>
			</div>

			{/* Delete Confirmation Modal */}
			{showDeleteConfirm && (
				<div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50">
					<div className="bg-white rounded-lg p-6 max-w-md w-full mx-4">
						<h3 className="text-lg font-semibold text-primary mb-2">
							Delete Campaign
						</h3>
						<p className="text-sm text-gray-70 mb-4">
							Are you sure you want to delete this campaign? This
							action cannot be undone.
						</p>
						<div className="mb-4">
							<label className="flex items-center gap-2 text-sm text-gray-80">
								<input
									type="checkbox"
									id="deleteProviders"
									className="rounded border-gray-30"
								/>
								<span>
									Also delete all provider records and events
								</span>
							</label>
						</div>
						<div className="flex gap-2 justify-end">
							<button
								onClick={() => setShowDeleteConfirm(false)}
								className="px-4 py-2 text-sm border border-gray-40 rounded-lg hover:bg-gray-20 transition-colors"
							>
								Cancel
							</button>
							<button
								onClick={() => {
									const deleteProviders =
										(
											document.getElementById(
												"deleteProviders",
											) as HTMLInputElement
										)?.checked || false;
									handleDelete(deleteProviders);
								}}
								className="px-4 py-2 text-sm bg-red-60 hover:bg-red-80 text-white rounded-lg transition-colors"
							>
								Delete
							</button>
						</div>
					</div>
				</div>
			)}

			{/* Status Metrics - Invited = providers we sent first mail to; others = backend counts */}
			<div className="flex flex-wrap gap-2">
				{PROVIDER_STATUS_ORDER.map((status) => {
					const rawCount = campaign.status_breakdown[status] ?? 0;
					const count =
						status === "INVITED"
							? campaign.total_providers -
								(campaign.status_breakdown["INVITED"] ?? 0)
							: rawCount;
					const color =
						STATUS_COLORS[status] ?? "bg-gray-20 text-gray-80";
					const label = STATUS_LABELS[status] ?? status;
					return (
						<span
							key={status}
							className={`inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full text-xs font-medium border border-gray-30 ${color}`}
						>
							<span className="font-bold text-primary">
								{count}
							</span>
							<span>{label}</span>
						</span>
					);
				})}
			</div>

			{/* Provider Inbox + Event Stream side-by-side */}
			<div className="grid grid-cols-1 lg:grid-cols-4 gap-6">
				{/* Provider Inbox (WhatsApp-style) */}
				<div className="lg:col-span-3 space-y-3">
					<ProviderInbox
						providers={campaign.providers}
						campaignId={campaignId}
						onSimulated={refresh}
					/>
				</div>

				{/* Event Stream */}
				<div className="lg:col-span-1">
					<EventStream />
				</div>
			</div>
		</div>
	);
}
