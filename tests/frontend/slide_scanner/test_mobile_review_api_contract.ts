import {
  slideScannerApi,
  type MobileHandoffResponse,
  type MobileReviewItemsResponse,
  type MobileRemoteDeleteResponse,
  type MobileReviewUpdateResponse
} from '../../../frontend/src/lib/api/slide-scanner';

type Assert<T extends true> = T;
type IsExact<A, B> =
  (<T>() => T extends A ? 1 : 2) extends
  (<T>() => T extends B ? 1 : 2) ? true : false;

type ApprovePayload = Awaited<ReturnType<typeof slideScannerApi.approveMobileItem>>;
type RejectPayload = Awaited<ReturnType<typeof slideScannerApi.rejectMobileItem>>;
type RemoteDeletePayload = Awaited<ReturnType<typeof slideScannerApi.remoteDeleteMobileItem>>;
type HandoffPayload = Awaited<ReturnType<typeof slideScannerApi.handoffMobileItem>>;
type ItemsPayload = Awaited<ReturnType<typeof slideScannerApi.getMobileReviewItems>>;

type _approveContract = Assert<IsExact<ApprovePayload, MobileReviewUpdateResponse>>;
type _rejectContract = Assert<IsExact<RejectPayload, MobileReviewUpdateResponse>>;
type _deleteContract = Assert<IsExact<RemoteDeletePayload, MobileRemoteDeleteResponse>>;
type _handoffContract = Assert<IsExact<HandoffPayload, MobileHandoffResponse>>;
type _itemsContract = Assert<IsExact<ItemsPayload, MobileReviewItemsResponse>>;

const approvePayloadExample: ApprovePayload = {
  id: 1,
  approval_status: 'APPROVED',
  remote_delete_status: 'PENDING',
  handoff_status: 'PENDING',
  slide_id: null,
  can_approve: false,
  can_remote_delete: true,
  can_handoff: false,
  can_open_editor: false
};
const rejectPayloadExample: RejectPayload = {
  id: 2,
  approval_status: 'REJECTED',
  remote_delete_status: 'PENDING',
  handoff_status: 'PENDING',
  slide_id: null,
  can_approve: false,
  can_remote_delete: false,
  can_handoff: false,
  can_open_editor: false,
  reason: 'blurred'
};
const deletePayloadExample: RemoteDeletePayload = {
  status: 'done',
  item_id: 3,
  results: {
    '/sdcard/DCIM/Camera/IMG_0001.jpg': true
  },
  approval_status: 'APPROVED',
  remote_delete_status: 'DONE',
  handoff_status: 'PENDING',
  slide_id: null,
  can_approve: false,
  can_remote_delete: false,
  can_handoff: true,
  can_open_editor: false
};
const handoffPayloadExample: HandoffPayload = {
  item_id: 3,
  slide_id: 91,
  slide_url: '/api/v1/ss/slides/91',
  approval_status: 'APPROVED',
  remote_delete_status: 'DONE',
  handoff_status: 'DONE',
  can_approve: false,
  can_remote_delete: false,
  can_handoff: false,
  can_open_editor: true
};

const itemsPromise = slideScannerApi.getMobileReviewItems({ approvalStatus: ['PENDING', 'APPROVED'] });
void itemsPromise;

void approvePayloadExample;
void rejectPayloadExample;
void deletePayloadExample;
void handoffPayloadExample;

export {};
