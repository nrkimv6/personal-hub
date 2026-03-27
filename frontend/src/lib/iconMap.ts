import { LayoutDashboard, Satellite, Download, Wrench, Settings, Code, Check, X, AlertTriangle, AlertCircle, Info } from 'lucide-svelte';

export const iconMap = {
	LayoutDashboard,
	Satellite,
	Download,
	Wrench,
	Settings,
	Code,
	Check,
	X,
	AlertTriangle,
	AlertCircle,
	Info
};

export type IconName = keyof typeof iconMap;
