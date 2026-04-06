import { LayoutDashboard, Satellite, Download, Wrench, Settings, Code, Check, X, AlertTriangle, AlertCircle, Info, Store, Plane, MessageCircle, Waves, Ticket } from 'lucide-svelte';

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
	Info,
	Store,
	Plane,
	MessageCircle,
	Waves,
	Ticket
};

export type IconName = keyof typeof iconMap;
