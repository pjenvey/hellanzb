class HellanzbController < ApplicationController
  before_filter :authorize, :defaults
  before_filter :load_queue, :except => :status
  
  require 'xmlrpc/client'
  
  def index
    @status = server.call("status")
  end
  
  def status
    @status = server.call("status")
    render :partial => "status", :locals => { :status => @status }
  end
  
  def update_order
    index = 0
    params[:nzb].each do |nzbId|
      if nzbId != @queue[index]["id"].to_s
        server.call('move', nzbId, index)
      end
      index += 1
    end
    load_queue
    render :partial => "queue_items", :locals => { :queue => @queue }
  end
  
  private
  def load_queue
    @queue = server.call('list')
  end
  
  def server()
    @server ||= XMLRPC::Client.new(@hnzb_server, "/", @hnzb_port, nil, nil, "hellanzb", @hnzb_password)
  end
end
